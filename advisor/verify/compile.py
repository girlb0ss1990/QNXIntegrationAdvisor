"""qcc compile checks for the generated kit and for step snippets (needs a local SDP)."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ..kit.generator import write_kit
from ..models import KitFile, Step
from ..sdp.locate import SdpInstall
from ..sdp.toolchain import CompileResult, qcc_compile

# Translation units in the kit: path pattern -> headers it covers.
UNITS = [
    (re.compile(r"^src/qnx_.+_resmgr\.c$"), re.compile(r"^src/.+_dcmd\.h$")),
    (re.compile(r"^src/.+ctl\.c$"), None),
    (re.compile(r"^tests/compat_selftest\.c$"), re.compile(r"^include/qnx_compat\.h$")),
]


def compile_kit(kit: list[KitFile], sdp: SdpInstall, archs: list[str], out_root: Path | None = None) -> list[CompileResult]:
    """Compiles each kit translation unit for each arch and records the outcome on the KitFiles."""
    results: list[CompileResult] = []
    with tempfile.TemporaryDirectory(prefix="qnx-advisor-kit-") as tmp:
        root = Path(tmp)
        write_kit(kit, root)
        status: dict[str, set[str]] = {}
        failed: set[str] = set()
        for unit_re, header_re in UNITS:
            for kf in kit:
                if not unit_re.match(kf.path):
                    continue
                for arch in archs:
                    out = (out_root or root / "build") / arch / Path(kf.path).stem
                    out.parent.mkdir(parents=True, exist_ok=True)
                    r = qcc_compile(sdp, arch, [root / kf.path], out=out,
                                    include_dirs=[root / "include", root / "src"], cwd=root)
                    results.append(r)
                    covered = [kf.path] + [h.path for h in kit if header_re and header_re.match(h.path)]
                    for p in covered:
                        if r.ok:
                            status.setdefault(p, set()).add(arch)
                        else:
                            failed.add(p)
        for kf in kit:
            if kf.path in failed:
                kf.qcc_compiled = "failed"
            elif kf.path in status:
                archs_ok = status[kf.path]
                kf.qcc_compiled = "both" if {"x86_64", "aarch64le"} <= archs_ok else sorted(archs_ok)[0]  # type: ignore[assignment]
    return results


SNIPPET_PRELUDE = """\
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <devctl.h>
#include <sys/neutrino.h>
#include <sys/procmgr.h>
extern char **environ;
static int chid, main_coid, tfd, cfd;
static pthread_mutex_t gains_lock;
static pthread_attr_t attr;
static const char *path = "x";
static char *arg;
enum { PULSE_CODE_FLUSH = _PULSE_CODE_MINAVAIL, PULSE_CODE_SHUTDOWN, SERVICE_UID = 1000, SERVICE_GID = 1000 };
#define PERIOD_NS 1000000L
static void do_work(void) {}
"""


def check_step_snippet(step: Step, sdp: SdpInstall, kit_include: Path | None, arch: str = "x86_64") -> str:
    """Best-effort `qcc -fsyntax-only` of a step's after_code inside a generic harness."""
    code = step.after_code
    if not code or step.category in ("toolchain_build", "deploy_verify") or "cmake" in code.lower()[:40]:
        return "skipped"
    includes = "\n".join(l for l in code.splitlines() if l.strip().startswith("#include"))
    body = "\n".join(l for l in code.splitlines() if not l.strip().startswith("#include"))
    has_fn = re.search(r"^\s*(static\s+)?[A-Za-z_][\w\s\*]*\([^;]*\)\s*$\s*\{", body, re.M)
    tu = SNIPPET_PRELUDE + includes + "\n" + (body if has_fn else
          "void advisor_snippet(void);\nvoid advisor_snippet(void)\n{\n" + body + "\n}\n")
    with tempfile.TemporaryDirectory(prefix="qnx-advisor-snip-") as tmp:
        src = Path(tmp) / "snippet.c"
        src.write_text(tu, encoding="utf-8")
        r = qcc_compile(sdp, arch, [src], syntax_only=True, include_dirs=[kit_include] if kit_include else [],
                        extra=["-Wno-unused-variable", "-Wno-unused-function", "-Wno-unused-parameter",
                               "-Wno-unused-but-set-variable", "-Wno-error"])
    return "passed" if r.ok else "failed"
