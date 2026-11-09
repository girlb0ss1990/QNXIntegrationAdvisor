"""Resource limits for ingest and scanning."""
from __future__ import annotations

import os
from pathlib import Path

CLONE_TIMEOUT_S = 90
MAX_REPO_BYTES = 300 * 1024 * 1024
MAX_FILE_BYTES = 1 * 1024 * 1024        # source files larger than this are skipped
MAX_SOURCE_FILES = 5000
MAX_CONCURRENT_JOBS = 2


def dir_size(root: Path, stop_at: int | None = None) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                continue
            if stop_at is not None and total >= stop_at:
                return total
    return total
