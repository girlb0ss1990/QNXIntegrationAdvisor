"""`make qnx-check`: render the kit for every sample and compile all translation units with qcc
for x86_64 and aarch64le. Writes docs/qnx-check-log.txt (our own build log, no SDP content)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from ..pipeline import Environment, analyze
from ..sdp.toolchain import qcc_version
from .compile import compile_kit

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    env = Environment.detect()
    if env.sdp is None:
        print("qnx-check needs a local QNX SDP 8.0 (source qnxsdp-env.sh).", file=sys.stderr)
        return 2
    archs = [a for a in ("x86_64", "aarch64le") if a in env.sdp.archs()]
    log = [f"qnx-check {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
           f"SDP {env.sdp.version}; compiler: {qcc_version(env.sdp)}; archs: {', '.join(archs)}", ""]
    total = ok = warnings = 0
    for sample in sorted((REPO / "samples").iterdir()):
        if not sample.is_dir():
            continue
        res = analyze(str(sample), env=env, compile_kit_files=False)
        log.append(f"== {sample.name} (service {res.report.service_name})")
        for r in compile_kit(res.report.kit, env.sdp, archs):
            total += 1
            ok += r.ok
            warnings += sum(d.severity == "warning" for d in r.diagnostics)
            cmd = " ".join(Path(c).name for c in r.command)     # basenames only: no local paths in the log
            log.append(f"  [{'OK ' if r.ok else 'ERR'}] {r.arch:9s} {cmd}")
            if r.output:
                log += ["      " + line for line in r.output.splitlines()[:40]]
    log += ["", f"{ok}/{total} compilations succeeded, {warnings} warning(s) (built with -Wall -Wextra -Werror)"]
    out = REPO / "docs" / "qnx-check-log.txt"
    out.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
