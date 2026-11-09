"""Minimal ELF .dynsym reader: fallback when nto*-nm cannot be run on this host.

Reads defined, global/weak FUNC/OBJECT symbols from 32/64-bit little/big-endian ELF
shared objects. Pure Python, read-only.
"""
from __future__ import annotations

import struct
from pathlib import Path

SHT_DYNSYM = 11
STB_GLOBAL, STB_WEAK = 1, 2
STT_OBJECT, STT_FUNC, STT_GNU_IFUNC = 1, 2, 10
SHN_UNDEF = 0


def dynamic_symbols(path: Path) -> list[str]:
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        return []
    is64 = data[4] == 2
    end = "<" if data[5] == 1 else ">"
    if is64:
        e_shoff, = struct.unpack_from(end + "Q", data, 0x28)
        e_shentsize, e_shnum = struct.unpack_from(end + "HH", data, 0x3A)
        sh_fmt, sym_fmt = end + "IIQQQQIIQQ", end + "IBBHQQ"
    else:
        e_shoff, = struct.unpack_from(end + "I", data, 0x20)
        e_shentsize, e_shnum = struct.unpack_from(end + "HH", data, 0x2E)
        sh_fmt, sym_fmt = end + "IIIIIIIIII", end + "IIIBBH"
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        if off + struct.calcsize(sh_fmt) > len(data):
            return []
        sections.append(struct.unpack_from(sh_fmt, data, off))
    out: list[str] = []
    for sh in sections:
        sh_type = sh[1]
        if sh_type != SHT_DYNSYM:
            continue
        sh_offset, sh_size, sh_link, sh_entsize = sh[4], sh[5], sh[6], sh[9]
        strtab = sections[sh_link]
        str_off = strtab[4]
        if not sh_entsize:
            continue
        for j in range(sh_size // sh_entsize):
            fields = struct.unpack_from(sym_fmt, data, sh_offset + j * sh_entsize)
            if is64:
                st_name, st_info, _other, st_shndx = fields[0], fields[1], fields[2], fields[3]
            else:
                st_name, st_info, st_shndx = fields[0], fields[3], fields[5]
            bind, typ = st_info >> 4, st_info & 0xF
            if st_shndx == SHN_UNDEF or bind not in (STB_GLOBAL, STB_WEAK):
                continue
            if typ not in (STT_FUNC, STT_OBJECT, STT_GNU_IFUNC):
                continue
            s = str_off + st_name
            e = data.find(b"\0", s)
            if e > s:
                out.append(data[s:e].decode("ascii", "replace"))
    return out
