"""Repository scanner: turns a checked-out repo into a ScanResult (spec 6.3)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..ingest.classify import RepoFiles, classify
from .ast_c_cpp import Hit, scan_file, tree_sitter_available
from .build_files import BuildInfo, parse_build_files

__all__ = ["Hit", "ScanResult", "scan_repo", "tree_sitter_available"]


@dataclass
class ScanResult:
    root: Path
    files: RepoFiles
    hits: list[Hit] = field(default_factory=list)
    build: BuildInfo = field(default_factory=BuildInfo)
    config_hits: list[Hit] = field(default_factory=list)
    repo_symbols: set[str] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)
    service_name: str = "service"
    main_struct: tuple[str, str] | None = None     # (type name, header path)
    parser: str = "tree-sitter"

    # convenience indexes
    def calls(self, name: str) -> list[Hit]:
        return [h for h in self.hits if h.kind == "call" and h.name == name]

    def has_call(self, *names: str) -> bool:
        s = set(names)
        return any(h.kind == "call" and h.name in s for h in self.hits)

    def has_token(self, *names: str) -> bool:
        s = set(names)
        return any(h.kind in ("token", "call") and h.name in s for h in self.hits)

    def source_text(self, rel: str) -> list[str]:
        try:
            return (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []


def _sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").lower()
    if not s or s[0].isdigit():
        s = "svc_" + s
    return s[:40]


def _detect_roles(sr: ScanResult) -> list[str]:
    roles = []
    dev_open = any(
        h.kind == "string" and re.match(r"^/dev/(?!null|zero|shm)", h.name) for h in sr.hits
    ) or any(h.kind == "include" and h.name.startswith(("linux/i2c", "linux/spi", "linux/can")) for h in sr.hits)
    has_loop_io = any(h.kind == "call" and h.in_loop and h.name in ("read", "write", "recv", "send") for h in sr.hits) \
        or sr.has_call("epoll_wait", "poll", "select")
    if dev_open and (has_loop_io or sr.has_call("pthread_create")):
        roles.append("device_service")
    timer = sr.has_call("timerfd_create", "timer_create", "clock_nanosleep") or any(
        h.kind == "call" and h.in_loop and h.name in ("usleep", "nanosleep") for h in sr.hits)
    rt = sr.has_token("SCHED_FIFO", "SCHED_RR") or sr.has_call("pthread_setschedparam", "sched_setscheduler")
    if timer and (rt or dev_open):
        roles.append("periodic_control_loop")
    if sr.has_call("daemon", "setsid") or any(c.name.endswith(".service") for c in sr.config_hits):
        roles.append("daemon")
    if sr.has_token("AF_UNIX", "AF_LOCAL") or sr.has_call("mq_open", "accept") or sr.has_call("shm_open"):
        roles.append("ipc_server")
    return roles


def _main_struct(sr: ScanResult) -> tuple[str, str] | None:
    """Most-referenced repo-defined typedef struct, used to wire the resmgr skeleton."""
    defs: dict[str, str] = {}
    for p in sr.files.sources:
        if p.suffix not in (".h", ".hpp", ".hh"):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"typedef\s+struct\s*\w*\s*\{[^}]*\}\s*([A-Za-z_]\w*)\s*;", txt, re.S):
            defs[m.group(1)] = sr.files.rel(p)
    if not defs:
        return None
    counts: Counter[str] = Counter()
    for p in sr.files.sources:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for name in defs:
            counts[name] += len(re.findall(rf"\b{re.escape(name)}\b", txt))
    name, _ = counts.most_common(1)[0]
    return name, defs[name]


def scan_repo(root: Path, interesting_tokens: set[str], config_globs: list[str]) -> ScanResult:
    import fnmatch

    files = classify(root)
    sr = ScanResult(root=root, files=files)
    sr.parser = "tree-sitter" if tree_sitter_available() else "regex-fallback"
    for p in files.sources:
        try:
            sr.hits.extend(scan_file(p, files.rel(p), interesting_tokens))
        except OSError:
            continue
    sr.repo_symbols = {h.name for h in sr.hits if h.kind == "funcdef"}
    sr.build = parse_build_files(files.build_files, files.rel)

    for p in files.config_files:
        rel = files.rel(p)
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if any(fnmatch.fnmatch(p.name, g) for g in config_globs):
            sr.config_hits.append(Hit("file", p.name, rel, 1, "\n".join(lines[:12])[:600]))
        for i, line in enumerate(lines, 1):
            if re.match(r"^\s*User\s*=\s*root\s*$", line):
                sr.config_hits.append(Hit("config_root", "User=root", rel, i, line.strip()))
            if re.match(r"^\s*CPUSchedulingPolicy\s*=\s*(fifo|rr)\s*$", line, re.I):
                sr.config_hits.append(Hit("config_rt", line.strip(), rel, i, line.strip()))

    sr.roles = _detect_roles(sr)
    name = sr.build.executables[0] if sr.build.executables else root.name
    sr.service_name = _sanitize(name)
    sr.main_struct = _main_struct(sr)
    return sr
