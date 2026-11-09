"""Sysroot indexer (spec 6.4): headers, macros and exported symbols of the *local* SDP.

The index is written to ~/.qnx-advisor/sysroot-index-<ver>.json and is never committed
or uploaded (spec section 4). It holds names only: header paths, macro names, symbol
names and the library each symbol comes from.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import elf
from .locate import ARCH_DIRS, SdpInstall
from .toolchain import nm_dynamic_symbols, qcc_version

INDEX_DIR = Path(os.environ.get("QNX_ADVISOR_HOME", Path.home() / ".qnx-advisor"))
DEFINE_RE = re.compile(rb"^\s*#\s*define\s+([A-Za-z_]\w*)", re.M)
PROTO_RE = re.compile(rb"\b([A-Za-z_]\w*)\s*\([^;{}()]*\)\s*(?:__[a-z_]+\s*(?:\([^)]*\))?\s*)*;")
ENUM_RE = re.compile(rb"\benum\b[^{;]*\{([^}]*)\}", re.S)
LIBNAME_RE = re.compile(r"^lib(.+?)\.so(\.\d+)*$")


@dataclass
class SysrootIndex:
    sdp_version: str
    qcc_version: str
    archs: list[str]
    headers: set[str] = field(default_factory=set)
    macros: set[str] = field(default_factory=set)
    declared: set[str] = field(default_factory=set)
    symbols: dict[str, list[str]] = field(default_factory=dict)   # symbol -> [lib names]
    libraries: set[str] = field(default_factory=set)
    created_utc: str = ""
    symbol_source: str = "nm"

    # --- queries -------------------------------------------------------------
    def has_symbol(self, name: str) -> bool:
        return name in self.symbols

    def lib_for(self, name: str) -> str | None:
        libs = self.symbols.get(name)
        if not libs:
            return None
        return "c" if "c" in libs else sorted(libs)[0]

    def has_header(self, h: str) -> bool:
        return h.lstrip("/") in self.headers

    def has_library(self, lib: str) -> bool:
        return lib in self.libraries

    def known(self, ident: str) -> bool:
        """An identifier the SDP provides: exported symbol, macro or declared function/enum."""
        return ident in self.symbols or ident in self.macros or ident in self.declared

    # --- persistence ---------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "sdp_version": self.sdp_version, "qcc_version": self.qcc_version, "archs": self.archs,
            "created_utc": self.created_utc, "symbol_source": self.symbol_source,
            "headers": sorted(self.headers), "macros": sorted(self.macros),
            "declared": sorted(self.declared), "libraries": sorted(self.libraries),
            "symbols": {k: sorted(v) for k, v in sorted(self.symbols.items())},
        }

    @classmethod
    def from_json(cls, d: dict) -> "SysrootIndex":
        return cls(
            sdp_version=d["sdp_version"], qcc_version=d.get("qcc_version", ""), archs=d.get("archs", []),
            headers=set(d.get("headers", [])), macros=set(d.get("macros", [])),
            declared=set(d.get("declared", [])), symbols={k: list(v) for k, v in d.get("symbols", {}).items()},
            libraries=set(d.get("libraries", [])), created_utc=d.get("created_utc", ""),
            symbol_source=d.get("symbol_source", "nm"),
        )

    def summary(self) -> dict:
        return {
            "sdp_version": self.sdp_version, "qcc_version": self.qcc_version, "archs": self.archs,
            "headers": len(self.headers), "symbols": len(self.symbols), "macros": len(self.macros),
            "libraries": len(self.libraries), "created_utc": self.created_utc, "symbol_source": self.symbol_source,
        }


def index_path(version: str) -> Path:
    return INDEX_DIR / f"sysroot-index-{re.sub(r'[^A-Za-z0-9_.-]', '_', version)}.json"


def _scan_headers(inc_root: Path, idx: SysrootIndex) -> None:
    for dirpath, _dirs, files in os.walk(inc_root):
        for fn in files:
            if not fn.endswith((".h", ".hpp")) and "." in fn:
                continue
            p = Path(dirpath) / fn
            idx.headers.add(p.relative_to(inc_root).as_posix())
            try:
                data = p.read_bytes()
            except OSError:
                continue
            idx.macros.update(m.decode() for m in DEFINE_RE.findall(data))
            idx.declared.update(m.decode() for m in PROTO_RE.findall(data))
            for body in ENUM_RE.findall(data):
                for item in body.split(b","):
                    m = re.match(rb"\s*([A-Za-z_]\w*)", item)
                    if m:
                        idx.declared.add(m.group(1).decode())


def _lib_dirs(sdp: SdpInstall, arch: str) -> list[Path]:
    base = sdp.qnx_target / ARCH_DIRS[arch]
    return [base / "lib", base / "usr" / "lib"]


def build_index(sdp: SdpInstall, progress=print) -> SysrootIndex:
    idx = SysrootIndex(sdp_version=sdp.version, qcc_version=qcc_version(sdp), archs=sdp.archs(),
                       created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    inc = sdp.qnx_target / "usr" / "include"
    progress(f"indexing headers under {inc}")
    _scan_headers(inc, idx)
    used_fallback = False
    for arch in idx.archs:
        for d in _lib_dirs(sdp, arch):
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                m = LIBNAME_RE.match(p.name)
                if p.name.endswith(".a"):
                    idx.libraries.add(p.name[3:-2] if p.name.startswith("lib") else p.name[:-2])
                    continue
                if not m or not p.is_file():
                    continue
                lib = m.group(1)
                idx.libraries.add(lib)
                syms = nm_dynamic_symbols(sdp, arch, p)
                if syms is None:
                    used_fallback = True
                    try:
                        syms = elf.dynamic_symbols(p)
                    except (OSError, ValueError, IndexError):
                        syms = []
                for s in syms:
                    libs = idx.symbols.setdefault(s, [])
                    if lib not in libs:
                        libs.append(lib)
        progress(f"{arch}: {len(idx.symbols)} symbols so far")
    idx.symbol_source = "elf-reader" if used_fallback else "nm"
    return idx


def save_index(idx: SysrootIndex) -> Path:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    p = index_path(idx.sdp_version)
    p.write_text(json.dumps(idx.to_json()), encoding="utf-8")
    return p


def load_index(version: str | None = None, path: Path | None = None) -> SysrootIndex | None:
    if path is None:
        if version:
            path = index_path(version)
        else:
            cands = sorted(INDEX_DIR.glob("sysroot-index-*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
                if INDEX_DIR.is_dir() else []
            path = cands[0] if cands else None
    if not path or not Path(path).exists():
        return None
    return SysrootIndex.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
