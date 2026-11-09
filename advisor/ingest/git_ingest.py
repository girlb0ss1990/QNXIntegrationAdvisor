"""Repository ingest: strict URL validation, shallow clone without a shell, size limits.

The user's repository is only *read*. Nothing from it is ever built or executed on the
host (spec G2).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .limits import CLONE_TIMEOUT_S, MAX_REPO_BYTES, dir_size

_HOSTS = r"(?:github\.com|gitlab\.com|bitbucket\.org)"
_NAME = r"[A-Za-z0-9_.-]{1,100}"
URL_RE = re.compile(
    rf"^https://{_HOSTS}/(?P<owner>{_NAME}(?:/{_NAME})*?)/(?P<repo>[A-Za-z0-9_-][A-Za-z0-9_.-]{{0,99}}?)(?:\.git)?"
    rf"(?:/(?:-/)?(?:tree|src)/(?P<ref>[A-Za-z0-9_./-]{{1,200}}))?/?$"
)


class IngestError(RuntimeError):
    pass


@dataclass
class IngestedRepo:
    root: Path
    source: str
    commit_sha: str
    is_temp: bool

    def cleanup(self) -> None:
        if self.is_temp and self.root.exists():
            shutil.rmtree(self.root.parent, ignore_errors=True)


def parse_url(url: str) -> tuple[str, str | None]:
    """Return (clone_url, ref) or raise IngestError."""
    m = URL_RE.match(url.strip())
    if not m:
        raise IngestError("Unsupported URL. Use https://github.com|gitlab.com|bitbucket.org/<owner>/<repo>[/tree/<ref>]")
    owner, repo, ref = m.group("owner"), m.group("repo"), m.group("ref")
    if ".." in owner or ".." in repo or (ref and ".." in ref):
        raise IngestError("Invalid path component in URL")
    host = url.split("/")[2]
    return f"https://{host}/{owner}/{repo}.git", ref


def _git(args: list[str], cwd: Path | None = None, timeout: int = CLONE_TIMEOUT_S) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo")
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except FileNotFoundError as e:
        raise IngestError("git is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise IngestError(f"git {args[0]} timed out after {timeout}s") from e
    if out.returncode != 0:
        raise IngestError(f"git {args[0]} failed: {out.stderr.strip()[:500]}")
    return out.stdout.strip()


def ingest(source: str, ref: str | None = None) -> IngestedRepo:
    """Clone a URL (shallow) or open a local directory read-only."""
    p = Path(source).expanduser()
    if not source.startswith("https://") and p.is_dir():
        root = p.resolve()
        sha = "local"
        if (root / ".git").exists():
            try:
                sha = _git(["rev-parse", "HEAD"], cwd=root, timeout=15)
            except IngestError:
                pass
        # Report the directory name only, so reports never carry local filesystem paths.
        return IngestedRepo(root=root, source=f"local:{root.name}", commit_sha=sha, is_temp=False)

    clone_url, url_ref = parse_url(source)
    ref = ref or url_ref
    if ref is not None and (ref.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", ref)):
        raise IngestError("Invalid ref")
    work = Path(tempfile.mkdtemp(prefix="qnx-advisor-"))
    dest = work / "repo"
    args = ["clone", "--depth", "1", "--filter=blob:limit=2m", "--no-tags", "--single-branch"]
    if ref:
        args += ["--branch", ref]
    args += ["--", clone_url, str(dest)]
    try:
        _git(args)
        if dir_size(dest, stop_at=MAX_REPO_BYTES + 1) > MAX_REPO_BYTES:
            raise IngestError(f"Repository exceeds the {MAX_REPO_BYTES // (1024 * 1024)} MB limit")
        sha = _git(["rev-parse", "HEAD"], cwd=dest, timeout=15)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return IngestedRepo(root=dest, source=source, commit_sha=sha, is_temp=True)
