"""The local QNX 8.0 QEMU target: where it lives, whether it is up, and starting it from the UI.

The VM is created and booted by qnx-target/vm/setup-vm.sh (mkqnximage from the user's own SDP). Its image
lives in ~/.qnx-advisor/vm (outside the repository: VM images are QNX software and are never committed),
and the script writes the VM's address to <vm dir>/ip. Starting is a fixed script with no user input.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
SETUP_VM = REPO / "qnx-target" / "vm" / "setup-vm.sh"
HOST_PREP = REPO / "qnx-target" / "vm" / "host-prep.sh"
_IP_RE = re.compile(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$")

_job: dict = {"state": "idle", "log": "", "started": 0.0, "target": None}
_lock = threading.Lock()


def vm_dir() -> Path:
    return Path(os.environ.get("QNX_ADVISOR_VM_DIR") or Path.home() / ".qnx-advisor" / "vm")


def saved_target() -> Optional[str]:
    """qnxuser@<ip> of the VM that setup-vm.sh last started, if any."""
    for d in (vm_dir(), REPO / "qnx-target" / "vm" / "local"):      # second: older layout
        try:
            ip = (d / "ip").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _IP_RE.match(ip):
            return f"qnxuser@{ip}"
    return None


def can_start() -> tuple[bool, str]:
    """Can this machine start the VM? (Linux/WSL with the SDP's mkqnximage on PATH.)"""
    if os.name == "nt":
        return False, "the QNX VM runs under Linux; start the advisor in QNX mode (start.bat does this when it finds the SDP in WSL)"
    if not os.environ.get("QNX_HOST"):
        return False, "QNX SDP environment not loaded (source ~/qnx800/qnxsdp-env.sh)"
    from shutil import which
    if not which("mkqnximage"):
        return False, "mkqnximage not found in the SDP"
    if not which("qemu-system-x86_64"):
        return False, "QEMU is not installed (sudo apt install qemu-system-x86 bridge-utils dnsmasq)"
    return True, ""


def status() -> dict:
    with _lock:
        return dict(_job)


def start_vm() -> dict:
    """Run setup-vm.sh in the background. Idempotent: a running VM is reused."""
    ok, why = can_start()
    if not ok:
        return {"state": "error", "log": why}
    with _lock:
        if _job["state"] == "starting":
            return dict(_job)
        _job.update(state="starting", log="", started=time.time(), target=None)

    def run() -> None:
        try:
            p = subprocess.Popen(["sh", str(SETUP_VM)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, cwd=str(REPO))
            assert p.stdout
            for line in p.stdout:
                if "post-quantum" in line or "store now, decrypt later" in line or "openssh.com/pq" in line:
                    continue                      # noisy OpenSSH notice about the target's older sshd
                with _lock:
                    _job["log"] = (_job["log"] + line)[-4000:]
            rc = p.wait(timeout=900)
        except (OSError, subprocess.SubprocessError) as e:
            with _lock:
                _job.update(state="error", log=_job["log"] + f"\n{e}")
            return
        with _lock:
            if rc == 0:
                _job.update(state="ready", target=saved_target())
            else:
                hint = (f"\nQEMU networking needs a one-time setup after each restart: sudo sh {HOST_PREP} "
                        f"{os.environ.get('USER', '')}" if rc == 2 else "")
                _job.update(state="error", log=_job["log"] + hint)

    threading.Thread(target=run, daemon=True).start()
    return status()
