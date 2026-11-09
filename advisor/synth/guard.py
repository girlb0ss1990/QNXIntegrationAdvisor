"""Hallucination guard (spec 6.5, required).

Every API-looking identifier and every <header.h> in LLM output must be found in the
local sysroot index, the rule DB, or the repository's own symbols. Sentences with
anything else are removed and counted. Numeric performance claims survive only when the
evidence is measured on the target.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..rules import rules_db_identifiers
from ..sdp.indexer import SysrootIndex

API_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
HEADER_RE = re.compile(r"<([A-Za-z0-9_./+-]+\.h(?:pp)?)>")
NUMERIC_CLAIM_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:ns|us|µs|ms|microseconds?|milliseconds?|nanoseconds?)\b|\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?x\b|"
    r"\b\d+\s*times\s+(?:faster|lower|less|better)|\bguarantee[sd]?\b)",
    re.I,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(`])")

# Words that look like calls in prose or C syntax but are not APIs.
NOT_APIS = {
    "if", "for", "while", "switch", "return", "sizeof", "defined", "e", "i", "eg", "ie", "etc", "see", "and", "or",
    "main", "via", "step", "steps", "optional", "recommended", "default", "note", "using", "with", "the",
}
# Standard C library names always acceptable (the guard targets OS/platform APIs).
STD_C = {
    "printf", "fprintf", "snprintf", "sprintf", "perror", "malloc", "calloc", "free", "realloc", "memset",
    "memcpy", "memmove", "strlen", "strcmp", "strncmp", "strcpy", "strncpy", "strtol", "strtoul", "atoi",
    "exit", "abort", "fopen", "fclose", "fgets", "fread", "fwrite", "sscanf", "scanf", "open", "close",
    "read", "write", "assert", "puts", "getopt", "strerror",
}


@dataclass
class GuardResult:
    removed: int = 0
    removed_items: list[str] = field(default_factory=list)


class Guard:
    def __init__(self, idx: SysrootIndex | None, repo_symbols: set[str]):
        self.idx = idx
        self.allowed = set(rules_db_identifiers()) | set(repo_symbols) | STD_C
        self.result = GuardResult()

    def api_ok(self, name: str) -> bool:
        if name.lower() in NOT_APIS or name in self.allowed:
            return True
        return bool(self.idx and self.idx.known(name))

    def header_ok(self, header: str) -> bool:
        if self.idx:
            return self.idx.has_header(header)
        # Without an SDP only headers named by the rule DB / feature catalogue are trusted.
        from ..rules import load_features, load_rules
        known = {h for f in load_features().values() for h in f.get("headers", [])}
        known |= {h for r in load_rules() for h in r.match.get("includes", [])}
        known |= {"sys/neutrino.h", "sys/dispatch.h", "sys/iofunc.h", "devctl.h", "sys/procmgr.h", "pthread.h",
                  "time.h", "poll.h", "spawn.h", "sys/slog2.h", "ha/ham.h", "sys/mman.h", "signal.h"}
        return header in known

    def _flag(self, what: str) -> None:
        self.result.removed += 1
        self.result.removed_items.append(what)

    def filter_apis(self, apis: list[str]) -> list[str]:
        out = []
        for a in apis:
            name = a.strip().rstrip("()")
            if self.api_ok(name):
                out.append(name)
            else:
                self._flag(f"api:{name}")
        return out

    def filter_headers(self, headers: list[str]) -> list[str]:
        out = []
        for h in headers:
            h = h.strip().strip("<>")
            if self.header_ok(h):
                out.append(h)
            else:
                self._flag(f"header:{h}")
        return out

    def filter_text(self, text: str, measured: bool = False) -> str:
        """Drop sentences that name unknown APIs/headers or make unmeasured numeric claims."""
        if not text:
            return text
        kept = []
        for sent in SENTENCE_SPLIT.split(text.strip()):
            bad = [m for m in API_RE.findall(sent) if not self.api_ok(m)]
            bad += [f"<{h}>" for h in HEADER_RE.findall(sent) if not self.header_ok(h)]
            if bad:
                self._flag("sentence:" + ",".join(bad))
                continue
            if not measured and NUMERIC_CLAIM_RE.search(sent):
                self._flag("numeric-claim")
                continue
            kept.append(sent)
        return " ".join(kept)

    def filter_code(self, code: str | None) -> str | None:
        """Code blocks: if they call unknown APIs, drop the block (it would not compile)."""
        if not code:
            return code
        stripped = re.sub(r"/\*.*?\*/|//[^\n]*|\"(?:[^\"\\]|\\.)*\"", "", code, flags=re.S)
        local_defs = set(re.findall(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", stripped))
        local_defs |= set(re.findall(r"#\s*define\s+([A-Za-z_]\w*)", stripped))
        bad = [m for m in API_RE.findall(stripped) if m not in local_defs and not self.api_ok(m)]
        bad += [h for h in HEADER_RE.findall(code) if not self.header_ok(h)]
        if bad:
            self._flag("code:" + ",".join(sorted(set(bad))))
            return None
        return code
