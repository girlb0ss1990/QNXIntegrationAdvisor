"""C/C++ extraction with tree-sitter (falls back to a regex scanner if tree-sitter is unavailable).

Extracts includes, call expressions, string literals, selected identifiers (tokens),
function definitions (repo symbols) and preprocessor context for each hit.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

GUARD_RE = re.compile(r"\b(__QNX__|__QNXNTO__|__linux__|__linux|__gnu_linux__|linux)\b")
LOOP_TYPES = {"for_statement", "while_statement", "do_statement"}
COND_TYPES = {"preproc_ifdef", "preproc_if", "preproc_elif", "preproc_elifdef"}


@dataclass
class Hit:
    kind: str              # include | call | string | token | funcdef
    name: str              # header path, function name, string content, identifier
    file: str              # repo-relative path
    line: int
    snippet: str
    guarded: bool = False  # inside a __QNX__/__linux__ conditional
    in_loop: bool = False
    args: str = ""         # call argument text (calls only, truncated)


_parsers: dict[str, object] = {}
_ts_failed = False


def _get_parser(lang: str):
    global _ts_failed
    if _ts_failed:
        return None
    if lang not in _parsers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from tree_sitter_languages import get_parser  # type: ignore
                _parsers[lang] = get_parser(lang)
        except Exception:
            _ts_failed = True
            return None
    return _parsers[lang]


def tree_sitter_available() -> bool:
    return _get_parser("c") is not None


def _line_text(lines: list[str], ln: int) -> str:
    return lines[ln - 1].strip()[:300] if 0 < ln <= len(lines) else ""


def scan_file(path: Path, rel: str, interesting_tokens: set[str]) -> list[Hit]:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    lang = "cpp" if path.suffix.lower() in {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".ipp"} else "c"
    parser = _get_parser(lang)
    if parser is None:
        return _scan_regex(lines, rel, interesting_tokens)
    tree = parser.parse(data)
    hits: list[Hit] = []

    # Iterative DFS carrying (guarded, in_loop) context.
    stack = [(tree.root_node, False, False)]
    while stack:
        node, guarded, in_loop = stack.pop()
        t = node.type
        if t in COND_TYPES:
            cond = node.child_by_field_name("name") or node.child_by_field_name("condition")
            if cond is not None and GUARD_RE.search(cond.text.decode("utf-8", "replace")):
                guarded = True
        if t in LOOP_TYPES:
            in_loop = True
        ln = node.start_point[0] + 1

        if t == "preproc_include":
            p = node.child_by_field_name("path")
            if p is not None:
                raw = p.text.decode("utf-8", "replace")
                if p.type == "system_lib_string":
                    hits.append(Hit("include", raw.strip("<>").strip(), rel, ln, _line_text(lines, ln), guarded))
                else:
                    hits.append(Hit("include_local", raw.strip('"'), rel, ln, _line_text(lines, ln), guarded))
        elif t == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None:
                name = fn.text.decode("utf-8", "replace")
                if fn.type in ("field_expression", "qualified_identifier", "scoped_identifier"):
                    name = re.split(r"(::|->|\.)", name)[-1]
                if re.fullmatch(r"[A-Za-z_]\w*", name):
                    a = node.child_by_field_name("arguments")
                    args = a.text.decode("utf-8", "replace")[:200] if a is not None else ""
                    hits.append(Hit("call", name, rel, ln, _line_text(lines, ln), guarded, in_loop, args))
        elif t == "string_literal":
            content = "".join(
                c.text.decode("utf-8", "replace") for c in node.children if c.type in ("string_content", "escape_sequence")
            )
            if content:
                hits.append(Hit("string", content, rel, ln, _line_text(lines, ln), guarded, in_loop))
        elif t == "identifier":
            name = node.text.decode("utf-8", "replace")
            if name in interesting_tokens:
                hits.append(Hit("token", name, rel, ln, _line_text(lines, ln), guarded, in_loop))
        elif t == "function_definition":
            d = node.child_by_field_name("declarator")
            while d is not None and d.type not in ("function_declarator",):
                d = d.child_by_field_name("declarator")
            if d is not None:
                ident = d.child_by_field_name("declarator")
                if ident is not None:
                    nm = re.split(r"::", ident.text.decode("utf-8", "replace"))[-1]
                    hits.append(Hit("funcdef", nm, rel, ln, _line_text(lines, ln), guarded))
        for c in reversed(node.children):
            stack.append((c, guarded, in_loop))
    return hits


# ---------------------------------------------------------------- regex fallback
_INC = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')
_COND_OPEN = re.compile(r"^\s*#\s*(if|ifdef|ifndef)\b(.*)")
_COND_ELSE = re.compile(r"^\s*#\s*(elif|else)\b(.*)")
_COND_END = re.compile(r"^\s*#\s*endif\b")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')
_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case", "defined", "__attribute__"}
_FUNCDEF = re.compile(r"^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?\s*$")


def _scan_regex(lines: list[str], rel: str, tokens: set[str]) -> list[Hit]:
    hits: list[Hit] = []
    cond_stack: list[bool] = []
    brace_depth = 0
    loop_braces: list[int] = []
    for i, line in enumerate(lines, 1):
        guarded = any(cond_stack)
        m = _COND_OPEN.match(line)
        if m:
            cond_stack.append(bool(GUARD_RE.search(m.group(2))))
            continue
        if _COND_ELSE.match(line):
            continue
        if _COND_END.match(line):
            if cond_stack:
                cond_stack.pop()
            continue
        m = _INC.match(line)
        if m:
            kind = "include" if m.group(1) == "<" else "include_local"
            hits.append(Hit(kind, m.group(2).strip(), rel, i, line.strip()[:300], guarded))
            continue
        code = re.sub(r"//.*$", "", line)
        if re.search(r"\b(for|while)\s*\(", code):
            loop_braces.append(brace_depth)
        in_loop = bool(loop_braces)
        for s in _STR.findall(code):
            hits.append(Hit("string", s, rel, i, line.strip()[:300], guarded, in_loop))
        code_nostr = _STR.sub('""', code)
        fd = _FUNCDEF.match(code_nostr)
        if fd and brace_depth == 0 and fd.group(1) not in _KEYWORDS:
            hits.append(Hit("funcdef", fd.group(1), rel, i, line.strip()[:300], guarded))
        else:
            for cm in _CALL.finditer(code_nostr):
                if cm.group(1) not in _KEYWORDS:
                    args = code_nostr[cm.end() - 1:][:200]
                    hits.append(Hit("call", cm.group(1), rel, i, line.strip()[:300], guarded, in_loop, args))
        for tok in tokens:
            if re.search(rf"\b{re.escape(tok)}\b", code_nostr):
                hits.append(Hit("token", tok, rel, i, line.strip()[:300], guarded, in_loop))
        brace_depth += code_nostr.count("{") - code_nostr.count("}")
        while loop_braces and brace_depth <= loop_braces[-1] and "}" in code_nostr:
            loop_braces.pop()
    return hits
