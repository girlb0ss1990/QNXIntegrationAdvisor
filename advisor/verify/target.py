"""Live target verification (mode M3, spec 6.8): build -> deploy -> verify -> benchmark -> record."""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

from ..models import IntegrationReport, VerificationRecord
from ..sdp.locate import SdpInstall
from .compile import compile_kit
from .deploy import DeployError, Target, reachable, scp_put, ssh

REMOTE_DIR = "/data/home/qnxuser"
ADVISORCTL = "/data/home/qnxuser/bin/advisorctl"   # installed by qnx-target/vm/install-agent.sh
Emit = Callable[[str, dict], None]


def _advisorctl(t: Target, args: list[str], timeout: int = 60) -> dict:
    r = ssh(t, [ADVISORCTL, *args], timeout=timeout)
    if r.returncode != 0 and not r.stdout.strip().startswith("{"):
        raise DeployError(f"advisorctl {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as e:
        raise DeployError(f"advisorctl {args[0]}: unparsable output") from e


def _target_kind(uname: str, arch: str) -> str:
    u = uname.lower()
    if "raspberry" in u or "rpi" in u:
        return "rpi5"
    return "qemu_aarch64le" if arch == "aarch64le" else "qemu_x86_64"


def run_verification(report: IntegrationReport, sdp: SdpInstall, target: Target, arch: str,
                     emit: Emit, kind: str | None = None) -> VerificationRecord:
    svc = report.service_name
    emit("qcc", {"message": f"building kit for {arch} with qcc"})
    with tempfile.TemporaryDirectory(prefix="qnx-advisor-verify-") as tmp:
        out_root = Path(tmp)
        results = compile_kit(report.kit, sdp, [arch], out_root=out_root)
        for r in results:
            emit("qcc", {"ok": r.ok, "arch": r.arch, "command": " ".join(r.command[-6:]),
                         "diagnostics": [d.__dict__ for d in r.diagnostics][:30], "output": r.output[-2000:]})
        if not all(r.ok for r in results):
            raise DeployError("kit did not compile; see qcc diagnostics")
        binaries = sorted(p for p in (out_root / arch).iterdir() if p.is_file())

        emit("deploy", {"message": f"checking {target.spec}"})
        ok, uname = reachable(target)
        if not ok:
            raise DeployError(f"target unreachable or not QNX: {uname}")
        scp_put(target, binaries, REMOTE_DIR)
        emit("deploy", {"message": f"copied {len(binaries)} binaries to {REMOTE_DIR}", "uname": uname})
        resmgr = next(p for p in binaries if p.name.endswith("_resmgr"))
        sha = hashlib.sha256(resmgr.read_bytes()).hexdigest()

    metrics: dict[str, float] = {}
    emit("verify", {"message": "advisorctl verify (spawn under /dev/advisor)"})
    v = _advisorctl(target, ["verify", f"{REMOTE_DIR}/{resmgr.name}", "--expect", f"/dev/{svc}",
                             "--timeout", "5000"], timeout=30)
    emit("verify", v)
    exit_status = int(v.get("exit_status", -1))
    if v.get("path_ready_ns", 0) > 0:
        metrics["resmgr_ready_ms"] = round(v["path_ready_ns"] / 1e6, 3)
    metrics["verify_wall_ms"] = round(v.get("wall_ns", 0) / 1e6, 3)
    st = ssh(target, [f"{REMOTE_DIR}/compat_selftest"], timeout=30)
    metrics["compat_selftest_exit"] = float(st.returncode)
    emit("verify", {"message": "compat_selftest", "exit": st.returncode, "output": st.stdout[-500:]})

    emit("bench", {"message": "IPC round-trip benchmark (MsgSend, 10000 iterations)"})
    ipc = _advisorctl(target, ["bench-ipc", "--iterations", "10000"], timeout=60)
    emit("bench", ipc)
    for k in ("min_ns", "p50_ns", "p99_ns", "max_ns"):
        if k in ipc:
            metrics[f"ipc_rtt_{k}"] = float(ipc[k])

    for load in (0, 4):
        label = "loaded" if load else "idle"
        emit("bench", {"message": f"timer benchmark 1 kHz for 5 s, {label} ({load} burner threads)"})
        tb = _advisorctl(target, ["bench-timer", "--period-us", "1000", "--duration-ms", "5000",
                                  "--priority", "40", "--load", str(load)], timeout=60)
        emit("bench", {**tb, "label": label})
        for k in ("p50_us", "p99_us", "max_us"):
            if k in tb:
                metrics[f"timer_late_{k.replace('_us', '')}_us_{label}"] = float(tb[k])

    rec = VerificationRecord(
        id="vr-" + uuid.uuid4().hex[:10], binary_sha256=sha, target_uname=uname,
        sdp_version=sdp.version, target_kind=kind or _target_kind(uname, arch),  # type: ignore[arg-type]
        exit_status=exit_status, metrics=metrics,
        timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        note="QEMU, indicative only" if "qemu" in (kind or _target_kind(uname, arch)) else "",
    )
    link_measurements(report, rec)
    return rec


def link_measurements(report: IntegrationReport, rec: VerificationRecord) -> None:
    """Pillar 2 items whose measurement_ref now has a value switch to evidence_type=measured."""
    for imp in report.pillar2_improvements:
        ref = imp.measurement_ref
        if ref and ":" not in ref and ref in rec.metrics:
            imp.evidence_type = "measured"
            imp.measurement_ref = f"{rec.id}:{ref}"
            imp.qnx_improvement += (f" Measured on {rec.target_kind} ({rec.note or 'hardware'}): "
                                    f"{ref} = {rec.metrics[ref]:g}.")
    report.verification.append(rec)
    report.mode = "M3"
