from __future__ import annotations

import io
import struct
import time
import zipfile

from fastapi.testclient import TestClient

from advisor.export import to_sarif
from advisor.sdp import elf
from advisor.server import create_app
from conftest import SAMPLES


def test_api_job_lifecycle():
    client = TestClient(create_app())
    env = client.get("/api/env").json()
    assert env["mode"] in ("M1", "M2", "M3") and "mode_reason" in env

    assert client.post("/api/jobs", json={"source": "https://evil.example/x/y"}).status_code == 400
    assert client.post("/api/jobs", json={"source": "/definitely/not/here"}).status_code == 400

    job = client.post("/api/jobs", json={"source": str(SAMPLES / "vitals-monitor")}).json()["job_id"]
    for _ in range(100):
        if client.get(f"/api/jobs/{job}").json()["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert client.get(f"/api/jobs/{job}").json()["status"] == "done"

    with client.stream("GET", f"/api/jobs/{job}/events") as s:
        body = "".join(s.iter_text())
    for stage in ("clone", "scan", "sysroot", "rules", "synth", "guard", "kit", "qcc", "done"):
        assert f"event: {stage}" in body

    report = client.get(f"/api/jobs/{job}/report").json()
    assert report["schema_version"] == "2.0" and report["repo_url"] == "local:vitals-monitor"
    assert "LNX-I2C" in {f["rule_id"] for f in report["findings"]}
    assert client.get(f"/api/jobs/{job}/report.md").text.startswith("# QNX 8.0 Integration Report")
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{job}/kit.zip").content))
    assert any(n.endswith("PORTING_GUIDE.md") for n in z.namelist())
    assert client.post(f"/api/jobs/{job}/verify", json={}).status_code in (400, 409)   # no SDP / no target


def test_sarif_shape():
    from advisor.pipeline import Environment, analyze
    r = analyze(str(SAMPLES / "motor-pid-controller"), env=Environment(None, None), compile_kit_files=False).report
    s = to_sarif(r)
    assert s["version"] == "2.1.0"
    res = s["runs"][0]["results"]
    assert res and all(x["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1 for x in res)


def _tiny_elf64(symbols: list[tuple[str, int, int]]) -> bytes:
    """Build a minimal little-endian ELF64 with .dynstr and .dynsym. symbols: (name, info, shndx)."""
    dynstr = b"\0" + b"".join(n.encode() + b"\0" for n, _, _ in symbols)
    syms = [struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0)]
    off = 1
    for n, info, shndx in symbols:
        syms.append(struct.pack("<IBBHQQ", off, info, 0, shndx, 0x1000, 16))
        off += len(n) + 1
    dynsym = b"".join(syms)
    data_off = 64
    dynstr_off, dynsym_off = data_off, data_off + len(dynstr)
    shoff = dynsym_off + len(dynsym)
    sh = [struct.pack("<IIQQQQIIQQ", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
          struct.pack("<IIQQQQIIQQ", 0, 3, 0, 0, dynstr_off, len(dynstr), 0, 0, 1, 0),
          struct.pack("<IIQQQQIIQQ", 0, 11, 0, 0, dynsym_off, len(dynsym), 1, 1, 8, 24)]
    hdr = b"\x7fELF" + bytes([2, 1, 1]) + b"\0" * 9
    hdr += struct.pack("<HHIQQQIHHHHHH", 3, 62, 1, 0, 0, shoff, 0, 64, 0, 0, 64, len(sh), 0)
    return hdr + dynstr + dynsym + b"".join(sh)


def test_elf_reader(tmp_path):
    func_global, obj_weak, func_local = (1 << 4) | 2, (2 << 4) | 1, (0 << 4) | 2
    p = tmp_path / "libfsnotify.so.1"
    p.write_bytes(_tiny_elf64([("inotify_add_watch", func_global, 7), ("weak_obj", obj_weak, 8),
                               ("local_fn", func_local, 7), ("undef_fn", func_global, 0)]))
    assert elf.dynamic_symbols(p) == ["inotify_add_watch", "weak_obj"]
    (tmp_path / "notelf.so").write_bytes(b"MZ....")
    assert elf.dynamic_symbols(tmp_path / "notelf.so") == []
