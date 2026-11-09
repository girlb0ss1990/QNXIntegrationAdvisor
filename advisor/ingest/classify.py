"""Classify repository files: sources, build systems, service configs, vendored deps."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from .limits import MAX_FILE_BYTES, MAX_SOURCE_FILES

VENDORED_DIRS = {"third_party", "third-party", "vendor", "external", "node_modules", ".git", "build", "deps"}
C_EXT = {".c", ".h"}
CPP_EXT = {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".ipp"}
OTHER_LANG = {".rs": "Rust", ".py": "Python", ".go": "Go"}

BUILD_FILES = {
    "CMakeLists.txt": "CMake", "Makefile": "Make", "makefile": "Make", "GNUmakefile": "Make",
    "meson.build": "Meson", "configure.ac": "Autotools", "configure.in": "Autotools",
    "BUILD": "Bazel", "BUILD.bazel": "Bazel", "WORKSPACE": "Bazel", "Cargo.toml": "Cargo",
}
CONFIG_PATTERNS = ["*.service", "*.socket", "*.timer", "*.rules", "Dockerfile", "package.xml", "*.launch.py", "*.launch", "*.sh"]


@dataclass
class RepoFiles:
    root: Path
    c_files: list[Path] = field(default_factory=list)
    cpp_files: list[Path] = field(default_factory=list)
    build_files: list[tuple[Path, str]] = field(default_factory=list)
    config_files: list[Path] = field(default_factory=list)
    vendored: list[str] = field(default_factory=list)
    languages: set[str] = field(default_factory=set)
    compile_commands: Path | None = None
    skipped_large: int = 0

    @property
    def sources(self) -> list[Path]:
        return self.c_files + self.cpp_files

    @property
    def build_systems(self) -> list[str]:
        return sorted({b for _, b in self.build_files})

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()


def classify(root: Path, include_vendored: bool = False) -> RepoFiles:
    rf = RepoFiles(root=root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        keep = []
        for dn in dirnames:
            if dn.startswith(".") and dn != ".github":
                continue
            if not include_vendored and dn in VENDORED_DIRS:
                if dn != ".git":
                    rf.vendored.append((d / dn).relative_to(root).as_posix())
                continue
            keep.append(dn)
        dirnames[:] = sorted(keep)
        for fn in sorted(filenames):
            p = d / fn
            if p.is_symlink():
                continue                       # never follow links out of the repo
            ext = p.suffix.lower()
            if fn in BUILD_FILES or fn.endswith(".cmake"):
                rf.build_files.append((p, BUILD_FILES.get(fn, "CMake")))
            if fn == "compile_commands.json":
                rf.compile_commands = p
            if any(fnmatch.fnmatch(fn, pat) for pat in CONFIG_PATTERNS):
                rf.config_files.append(p)
            if ext in C_EXT or ext in CPP_EXT:
                try:
                    if p.stat().st_size > MAX_FILE_BYTES:
                        rf.skipped_large += 1
                        continue
                except OSError:
                    continue
                count += 1
                if count > MAX_SOURCE_FILES:
                    continue
                if ext in C_EXT:
                    rf.c_files.append(p)
                    rf.languages.add("C")
                else:
                    rf.cpp_files.append(p)
                    rf.languages.add("C++")
            elif ext in OTHER_LANG:
                rf.languages.add(OTHER_LANG[ext])
    # A .h file in a pure C++ project is C++.
    if "C++" in rf.languages and not any(p.suffix == ".c" for p in rf.c_files):
        rf.languages.discard("C")
    return rf
