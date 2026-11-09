"""Porting-kit generator (spec 6.6): renders Jinja2 templates per repository."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..models import IntegrationReport, KitFile

TEMPLATES = Path(__file__).with_name("templates")
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), undefined=StrictUndefined,
                   keep_trailing_newline=True, autoescape=False)

# (template, output path pattern, description, compile unit?)
KIT_LAYOUT = [
    ("qnx8-toolchain.cmake.j2", "cmake/qnx8-toolchain.cmake", "CMake toolchain file for qcc/q++ (x86_64, aarch64le)", False),
    ("qnx8.cmake.j2", "cmake/qnx8.cmake", "if(QNX) snippet to include from the repo's CMakeLists.txt", False),
    ("qnx_compat.h.j2", "include/qnx_compat.h", "Only the compatibility shims this repo needs", False),
    ("resmgr.c.j2", "src/qnx_{svc}_resmgr.c", "Resource manager skeleton at /dev/{svc} (dispatch/iofunc, pulse timer, procmgr_ability)", True),
    ("dcmd.h.j2", "src/{svc}_dcmd.h", "devctl() command definitions (__DIOF/__DIOT)", False),
    ("client.c.j2", "src/{svc}ctl.c", "Client: open + devctl, prints JSON", True),
    ("compat_selftest.c.j2", "tests/compat_selftest.c", "Runs every shim in qnx_compat.h on the target", True),
    ("Makefile.qnx.j2", "Makefile.qnx", "Builds the kit binaries with qcc", False),
    ("run-qemu.sh.j2", "target/run-qemu.sh", "mkqnximage QEMU target + copy binaries over SSH", False),
    ("image.build.j2", "target/{svc}.build", "Advanced: mkifs buildfile fragment", False),
    ("PORTING_GUIDE.md.j2", "PORTING_GUIDE.md", "Per-repo codelab version of Pillar 3", False),
]


@dataclass
class KitContext:
    repo_name: str
    svc: str
    arch: str = "x86_64"
    target: str = ""
    main_struct: tuple[str, str] | None = None
    period_ms: int = 10
    pulse_prio: int = 21


def kit_variables(report: IntegrationReport, ctx: KitContext) -> dict:
    ids = {f.rule_id for f in report.findings}
    link_libs = sorted({lib for f in report.findings for lib in f.link_libs})
    reasons = []
    for f in report.findings:
        for lib in f.link_libs:
            reasons.append(f"{lib} ({f.title})")
    drop_libs = []
    for f in report.findings:
        if f.rule_id == "LNX-LIBS" and f.sysroot_status == "missing":
            drop_libs = sorted(re.findall(r"lib(pthread|rt|dl)\b", f.sysroot_detail))
        elif f.rule_id == "LNX-LIBS" and f.sysroot_status == "unknown_no_sdp":
            drop_libs = sorted({lib for loc in f.locations for lib in _libs_in(loc.snippet)})
    if report.sysroot_verified:
        sysroot_note = f"APIs were checked against the local QNX SDP {report.sdp_version} sysroot."
    else:
        sysroot_note = "No QNX SDP was found, so availability is based on rule knowledge and is unverified against a sysroot."
    return dict(
        repo_name=ctx.repo_name, svc=ctx.svc, SVC=ctx.svc.upper(), arch=ctx.arch,
        target=ctx.target or ctx.svc, main_struct=ctx.main_struct, period_ms=ctx.period_ms,
        pulse_prio=ctx.pulse_prio, link_libs=link_libs, lib_reasons=", ".join(sorted(set(reasons))) or "none",
        drop_libs=drop_libs, need_timer=bool(ids & {"LNX-TIMERFD", "LNX-PERIODIC-SLEEP"}),
        need_notifier="LNX-EVENTFD" in ids, findings=report.findings, steps=report.pillar3_steps,
        score=report.readiness_score, commit=report.commit_sha[:12], sysroot_note=sysroot_note,
        sysroot_verified=report.sysroot_verified,
        mode_label={"M1": "deterministic mode", "M2": "AI-assisted mode", "M3": "live-target mode"}[report.mode],
    )


def _libs_in(snippet: str) -> set[str]:
    return set(re.findall(r"(?:-l|\b)(pthread|rt|dl)\b", snippet))


def generate_kit(report: IntegrationReport, ctx: KitContext) -> list[KitFile]:
    v = kit_variables(report, ctx)
    files: list[KitFile] = []
    for tpl, out, desc, compiled in KIT_LAYOUT:
        content = _env.get_template(tpl).render(**v)
        files.append(KitFile(
            path=out.format(svc=ctx.svc), description=desc.format(svc=ctx.svc), content=content,
            qcc_compiled="skipped" if compiled or out.endswith((".h",)) else "not_applicable",
        ))
    return files


def render_resmgr_excerpt(report: IntegrationReport, ctx: KitContext) -> str:
    """The io_devctl() handler, shown as the 'after' code of the resmgr-conversion step."""
    src = _env.get_template("resmgr.c.j2").render(**kit_variables(report, ctx))
    start = src.find("static int io_devctl(")
    end = src.find("/* ------------------------------------------------------------------ timer pulse */")
    return src[start:end].rstrip() if start != -1 and end != -1 else ""


def kit_zip(kit: list[KitFile], root_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in kit:
            info = zipfile.ZipInfo(f"{root_name}/{f.path}")
            info.external_attr = (0o755 if f.path.endswith(".sh") else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.content)
    return buf.getvalue()


def write_kit(kit: list[KitFile], out_dir: Path) -> None:
    for f in kit:
        p = out_dir / f.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f.content, encoding="utf-8", newline="\n")
        if f.path.endswith(".sh"):
            p.chmod(0o755)
