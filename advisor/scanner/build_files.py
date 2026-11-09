"""CMake and Make parsing: link libraries, compiler flags, find_package, executables."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .ast_c_cpp import Hit

_CMAKE_KEYWORDS = {"PUBLIC", "PRIVATE", "INTERFACE", "debug", "optimized", "general", "LINK_PUBLIC", "LINK_PRIVATE"}


@dataclass
class BuildInfo:
    link_libs: dict[str, list[Hit]] = field(default_factory=dict)   # lib -> hits
    flag_lines: list[Hit] = field(default_factory=list)              # every non-comment line, for regex rules
    find_packages: set[str] = field(default_factory=set)
    executables: list[str] = field(default_factory=list)
    uses_threads_target: bool = False

    def add_lib(self, lib: str, hit: Hit) -> None:
        self.link_libs.setdefault(lib, []).append(hit)


def _strip_cmake_comment(line: str) -> str:
    return re.sub(r"(?<!\\)#.*$", "", line)


def parse_cmake(path: Path, rel: str, info: BuildInfo) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    for i, raw in enumerate(lines, 1):
        line = _strip_cmake_comment(raw)
        if line.strip():
            info.flag_lines.append(Hit("build_line", line.strip(), rel, i, raw.strip()[:300]))
    # Multi-line commands: join and keep start line.
    for m in re.finditer(r"(?is)\b(target_link_libraries|link_libraries|find_package|add_executable)\s*\(([^)]*)\)", text):
        cmd = m.group(1).lower()
        start_line = text.count("\n", 0, m.start()) + 1
        args = _strip_cmake_comment(m.group(2)).split()
        snippet = lines[start_line - 1].strip()[:300] if start_line <= len(lines) else ""
        if cmd == "find_package" and args:
            info.find_packages.add(args[0])
        elif cmd == "add_executable" and args:
            info.executables.append(args[0])
        elif cmd in ("target_link_libraries", "link_libraries"):
            items = args[1:] if cmd == "target_link_libraries" else args
            for a in items:
                if a in _CMAKE_KEYWORDS or a.startswith("$"):
                    continue
                if a == "Threads::Threads":
                    info.uses_threads_target = True
                    continue
                if "::" in a:
                    continue
                lib = a[2:] if a.startswith("-l") else a
                if re.fullmatch(r"[A-Za-z0-9_+.-]+", lib):
                    info.add_lib(lib, Hit("link_lib", lib, rel, start_line, snippet))


def parse_make(path: Path, rel: str, info: BuildInfo) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    first_target = None
    for i, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(?<!\\)#.*$", "", raw)
        if not line.strip():
            continue
        info.flag_lines.append(Hit("build_line", line.strip(), rel, i, raw.strip()[:300]))
        for lm in re.finditer(r"(?<![\w-])-l([A-Za-z0-9_+.-]+)", line):
            info.add_lib(lm.group(1), Hit("link_lib", lm.group(1), rel, i, raw.strip()[:300]))
        tm = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", line)
        if tm and first_target is None and not tm.group(1).startswith(".") and tm.group(1) not in ("all", "install", "clean"):
            first_target = tm.group(1)
    if first_target and "." not in first_target:
        info.executables.append(first_target)


def parse_build_files(build_files: list[tuple[Path, str]], rel) -> BuildInfo:
    info = BuildInfo()
    for p, kind in build_files:
        try:
            if kind == "CMake":
                parse_cmake(p, rel(p), info)
            elif kind == "Make":
                parse_make(p, rel(p), info)
            else:
                text = p.read_text(encoding="utf-8", errors="replace")
                for i, raw in enumerate(text.splitlines(), 1):
                    if raw.strip():
                        info.flag_lines.append(Hit("build_line", raw.strip(), rel(p), i, raw.strip()[:300]))
        except OSError:
            continue
    return info
