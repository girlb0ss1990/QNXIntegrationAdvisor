"""Thin wrappers around the SDP's own qcc and nto*-nm (argument arrays, no shell)."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .locate import SdpInstall

QCC_VARIANT = {"x86_64": "gcc_ntox86_64", "aarch64le": "gcc_ntoaarch64le"}
NM_TOOL = {"x86_64": "ntox86_64-nm", "aarch64le": "ntoaarch64-nm"}
DIAG_RE = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>error|warning|note|fatal error):\s*(?P<msg>.*)$", re.M)


@dataclass
class Diagnostic:
    file: str
    line: int
    col: int
    severity: str
    message: str


@dataclass
class CompileResult:
    ok: bool
    arch: str
    command: list[str]
    output: str
    diagnostics: list[Diagnostic]


def sdp_env(sdp: SdpInstall) -> dict[str, str]:
    env = dict(os.environ)
    env["QNX_HOST"] = str(sdp.qnx_host)
    env["QNX_TARGET"] = str(sdp.qnx_target)
    env["PATH"] = str(sdp.bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def _run(cmd: list[str], sdp: SdpInstall, timeout: int = 120, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=sdp_env(sdp), capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False)


def qcc_path(sdp: SdpInstall) -> str | None:
    p = sdp.tool("qcc")
    return str(p) if p else None


def qcc_version(sdp: SdpInstall) -> str:
    """Version string reported by the installed compiler (spec E13: never hardcoded)."""
    for arch in ("x86_64", "aarch64le"):
        gcc = sdp.tool(f"nto{'x86_64' if arch == 'x86_64' else 'aarch64'}-gcc")
        if gcc:
            try:
                out = _run([str(gcc), "--version"], sdp, timeout=30).stdout
                if out:
                    return out.splitlines()[0].strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
    q = qcc_path(sdp)
    if q:
        try:
            r = _run([q, "-V"], sdp, timeout=30)
            txt = (r.stdout + r.stderr).strip()
            return txt.splitlines()[0] if txt else "qcc (version unknown)"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "unavailable"


def parse_diagnostics(output: str) -> list[Diagnostic]:
    return [
        Diagnostic(m["file"], int(m["line"]), int(m["col"] or 0), m["sev"], m["msg"].strip())
        for m in DIAG_RE.finditer(output)
    ]


def qcc_compile(sdp: SdpInstall, arch: str, sources: list[Path], out: Path | None = None,
                include_dirs: list[Path] | None = None, libs: list[str] | None = None,
                syntax_only: bool = False, extra: list[str] | None = None, cwd: Path | None = None) -> CompileResult:
    q = qcc_path(sdp)
    if not q:
        return CompileResult(False, arch, [], "qcc not found in SDP", [])
    cmd = [q, f"-V{QCC_VARIANT[arch]}", "-Wall", "-Wextra", "-Werror", "-std=gnu11", "-D_QNX_SOURCE"]
    for d in include_dirs or []:
        cmd += ["-I", str(d)]
    cmd += extra or []
    if syntax_only:
        cmd.append("-fsyntax-only")
    cmd += [str(s) for s in sources]
    if not syntax_only:
        cmd += ["-o", str(out or Path("a.out"))]
        cmd += [f"-l{lib}" for lib in libs or []]
    try:
        r = _run(cmd, sdp, timeout=180, cwd=cwd)
    except subprocess.TimeoutExpired:
        return CompileResult(False, arch, cmd, "qcc timed out", [])
    output = (r.stdout + r.stderr).strip()
    return CompileResult(r.returncode == 0, arch, cmd, output, parse_diagnostics(output))


def nm_dynamic_symbols(sdp: SdpInstall, arch: str, lib: Path) -> list[str] | None:
    """Defined dynamic symbols via the SDP's nto<arch>-nm. None if the tool is unavailable."""
    tool = sdp.tool(NM_TOOL[arch])
    if not tool:
        return None
    try:
        r = _run([str(tool), "-D", "--defined-only", str(lib)], sdp, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return []
    syms = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] in ("T", "W", "D", "B", "R", "V", "i", "u"):
            syms.append(parts[2].split("@")[0])
    return syms
