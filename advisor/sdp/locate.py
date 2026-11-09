"""Locate a local QNX SDP 8.0 installation (never bundled, never uploaded)."""
from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

ARCH_DIRS = {"x86_64": "x86_64", "aarch64le": "aarch64le"}


@dataclass
class SdpInstall:
    root: Path | None
    qnx_host: Path
    qnx_target: Path
    version: str

    @property
    def bin_dir(self) -> Path:
        return self.qnx_host / "usr" / "bin"

    def archs(self) -> list[str]:
        return [a for a, d in ARCH_DIRS.items() if (self.qnx_target / d).is_dir()]

    def tool(self, name: str) -> Path | None:
        for cand in (name, name + ".exe", name + ".bat"):
            p = self.bin_dir / cand
            if p.exists():
                return p
        return None


def _version_from_path(p: Path) -> str:
    for part in reversed(p.parts):
        m = re.fullmatch(r"qnx(\d)(\d)(\d)", part.lower())
        if m:
            return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return "8.0 (unknown patch)"


def _host_dir(root: Path) -> Path | None:
    sysname = {"Linux": "linux", "Windows": "win64", "Darwin": "darwin"}.get(platform.system(), "linux")
    for cand in (root / "host" / sysname / "x86_64", root / "host" / "linux" / "x86_64"):
        if cand.is_dir():
            return cand
    return None


def locate_sdp(explicit: str | None = None) -> SdpInstall | None:
    """Find the SDP from --sdp, from QNX_HOST/QNX_TARGET, or from ~/qnx800."""
    version_override = os.environ.get("QNX_SDP_VERSION")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        host, target = _host_dir(root), root / "target" / "qnx"
        if host and target.is_dir():
            return SdpInstall(root, host, target, version_override or _version_from_path(root))
        return None
    qh, qt = os.environ.get("QNX_HOST"), os.environ.get("QNX_TARGET")
    if qh and qt and Path(qh).is_dir() and Path(qt).is_dir():
        root = Path(qt).resolve().parent.parent
        return SdpInstall(root, Path(qh).resolve(), Path(qt).resolve(), version_override or _version_from_path(root))
    for guess in (Path.home() / "qnx800", Path("/opt/qnx800"), Path("C:/qnx800")):
        if guess.is_dir():
            found = locate_sdp(str(guess))
            if found:
                return found
    return None
