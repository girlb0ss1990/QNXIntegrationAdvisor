"""SSH/SCP to the QNX target. Argument arrays only; remote commands are shell-quoted."""
from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}@[A-Za-z0-9_.:-]{1,253}$")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]


class DeployError(RuntimeError):
    pass


@dataclass
class Target:
    spec: str              # user@host
    port: int = 22
    key: str | None = None

    def __post_init__(self):
        if not TARGET_RE.match(self.spec):
            raise DeployError(f"invalid target '{self.spec}', expected user@host")

    def _opts(self, scp: bool = False) -> list[str]:
        o = list(SSH_OPTS)
        o += ["-P" if scp else "-p", str(self.port)]
        if self.key:
            o += ["-i", self.key]
        return o


def ssh(t: Target, argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    remote = " ".join(shlex.quote(a) for a in argv)
    try:
        return subprocess.run(["ssh", *t._opts(), t.spec, remote], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise DeployError("ssh client not found") from e
    except subprocess.TimeoutExpired as e:
        raise DeployError(f"ssh timed out: {' '.join(argv)}") from e


def scp_put(t: Target, files: list[Path], remote_dir: str, timeout: int = 120) -> None:
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", remote_dir):
        raise DeployError("invalid remote directory")
    try:
        r = subprocess.run(["scp", *t._opts(scp=True), *[str(f) for f in files], f"{t.spec}:{remote_dir}/"],
                           capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise DeployError("scp not found") from e
    except subprocess.TimeoutExpired as e:
        raise DeployError("scp timed out") from e
    if r.returncode != 0:
        raise DeployError(f"scp failed: {r.stderr.strip()[:300]}")


def reachable(t: Target) -> tuple[bool, str]:
    try:
        r = ssh(t, ["uname", "-a"], timeout=10)
    except DeployError as e:
        return False, str(e)
    if r.returncode != 0:
        return False, r.stderr.strip()[:200] or "ssh failed"
    out = r.stdout.strip()
    return out.startswith("QNX"), out
