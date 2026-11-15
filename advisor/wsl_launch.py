"""Windows "QNX mode": run the advisor inside WSL, where the QNX SDP (qcc, mkqnximage) and the QEMU target live.

start.bat calls `python -m advisor.cli qnx-mode`. This module
  1. finds the WSL user that owns the QNX SDP (the QNX licence lives in that user's home),
  2. prepares KVM and the QEMU bridge as root (WSL needs no password for that; forgotten on every WSL restart),
  3. runs start.sh from this same folder inside WSL, and opens the Windows browser once the server answers
     (WSL2 forwards localhost to Windows),
  4. asks the server to boot the QNX virtual machine in the background.
Only fixed commands are run; the folder path is passed as an argument, never spliced into shell text.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

from .settings import find_wsl_sdp

REPO = Path(__file__).resolve().parents[1]


def sdp_user() -> Optional[str]:
    found = find_wsl_sdp()
    sdp = (found or {}).get("sdp") or ""
    m = re.match(r"^/home/([A-Za-z0-9._-]+)/qnx[0-9]+$", sdp)
    if m:
        return m.group(1)
    return "root" if sdp.startswith("/root/") else None


def _wsl_path(user: str, win_path: Path) -> Optional[str]:
    try:
        r = subprocess.run(["wsl.exe", "-u", user, "-e", "wslpath", "-a", str(win_path)],
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.decode("utf-8", "replace").strip()
    return out if r.returncode == 0 and out.startswith("/") else None


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "api/env", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def run(port: int = 8765, start_vm: bool = True, open_browser: bool = True) -> int:
    user = sdp_user()
    if not user:
        print("  No QNX SDP was found inside WSL.", file=sys.stderr)
        return 3
    repo = _wsl_path(user, REPO)
    if not repo:
        print("  Could not open this folder from WSL.", file=sys.stderr)
        return 3
    url = f"http://127.0.0.1:{port}/"
    if _up(url):
        print(f"  The advisor is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    print(f"  QNX mode: running inside WSL as '{user}' with the QNX SDP.")
    print("  Preparing the QEMU virtual machine support (KVM + network bridge) ...")
    subprocess.run(["wsl.exe", "-u", "root", "-e", "sh", f"{repo}/qnx-target/vm/host-prep.sh", user],
                   timeout=120, check=False)

    state = {"up": False}

    def watch() -> None:
        for _ in range(600):                     # first run installs Python packages inside WSL: be patient
            time.sleep(1)
            if _up(url):
                state["up"] = True
                print(f"\n  QNX Integration Advisor (QNX mode) is ready: {url}\n  Close this window to stop it.\n")
                if open_browser:
                    webbrowser.open(url)
                if start_vm:
                    try:
                        req = urllib.request.Request(url + "api/setup/start-vm", data=b"{}", method="POST",
                                                     headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=10) as r:
                            st = json.loads(r.read() or b"{}")
                        print(f"  QNX virtual machine: {st.get('state', '?')} (progress is shown on the Setup page)")
                    except OSError as e:
                        print(f"  Could not start the QNX virtual machine automatically: {e}")
                return

    threading.Thread(target=watch, daemon=True).start()
    # Share the AI settings saved on the Windows side (Setup page) with the server running in WSL.
    from .settings import SETTINGS_PATH
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings_wsl = _wsl_path(user, SETTINGS_PATH) or ""
    script = ('cd "$1" && export QNX_ADVISOR_NO_OPEN=1 PORT="$2" && '
              '{ [ -z "$3" ] || export QNX_ADVISOR_SETTINGS="$3"; } && exec bash ./start.sh')
    try:
        rc = subprocess.run(["wsl.exe", "-u", user, "-e", "bash", "-lc", script, "qnx-mode", repo, str(port),
                             settings_wsl],
                            check=False).returncode
    except KeyboardInterrupt:
        rc = 0
    if not state["up"]:
        return 3                                # never came up: let start.bat fall back to Windows mode
    return 0 if rc in (0, 130, 143) else rc
