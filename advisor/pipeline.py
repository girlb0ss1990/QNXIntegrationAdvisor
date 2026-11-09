"""End-to-end analysis pipeline: ingest -> scan -> sysroot -> rules -> synth -> guard -> kit -> qcc."""
from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ingest import IngestedRepo, ingest
from .kit.generator import KitContext, generate_kit, render_resmgr_excerpt, write_kit
from .models import IntegrationReport
from .rules import config_globs, interesting_tokens, ruleset_hash
from .rules.matcher import match_rules
from .rules.score import readiness_score
from .scanner import ScanResult, scan_repo
from .sdp import SdpInstall, SysrootIndex, load_index, locate_sdp
from .synth import deterministic as det

Emit = Callable[[str, dict], None]


def _noop(_e: str, _d: dict) -> None:
    pass


@dataclass
class Environment:
    sdp: SdpInstall | None
    index: SysrootIndex | None

    @classmethod
    def detect(cls, sdp_path: str | None = None) -> "Environment":
        sdp = locate_sdp(sdp_path)
        idx = None
        if sdp:
            idx = load_index(sdp.version)
        if idx is None:
            idx = load_index()          # most recent index, e.g. built on this machine earlier
            if idx is not None and sdp is not None and idx.sdp_version != sdp.version:
                idx = None
        return cls(sdp=sdp, index=idx)


@dataclass
class AnalysisResult:
    report: IntegrationReport
    scan: ScanResult
    repo: IngestedRepo
    kit_ctx: KitContext
    messages: list[str]


def _period_ms(sr: ScanResult) -> int:
    """Period for the resmgr's tick pulse, from a LOOP_HZ-style #define if the repo has one."""
    for p in sr.files.sources:
        txt = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"#\s*define\s+\w*(?:HZ|RATE)\w*\s+(\d+)", txt)
        if m and int(m.group(1)) > 0:
            return max(1, 1000 // int(m.group(1)))
    return 1 if "periodic_control_loop" in sr.roles else 100


def analyze(source: str, ref: str | None = None, arch: str = "x86_64", use_llm: bool = False,
            env: Environment | None = None, emit: Emit = _noop, compile_kit_files: bool = True,
            keep_repo: bool = False) -> AnalysisResult:
    env = env or Environment.detect()
    messages: list[str] = []
    emit("clone", {"message": f"ingesting {source}"})
    repo = ingest(source, ref)
    try:
        emit("clone", {"message": f"commit {repo.commit_sha[:12]}", "commit": repo.commit_sha})

        sr = scan_repo(repo.root, interesting_tokens(), config_globs())
        emit("scan", {"message": f"scanned {len(sr.files.sources)} C/C++ files with {sr.parser}",
                      "files": len(sr.files.sources), "build_systems": sr.files.build_systems,
                      "roles": sr.roles, "vendored_skipped": sr.files.vendored})

        idx = env.index
        if idx:
            emit("sysroot", {"message": f"using local SDP {idx.sdp_version} index ({len(idx.symbols)} symbols)",
                             "verified": True})
        else:
            emit("sysroot", {"message": "no SDP index: availability is unverified against a sysroot", "verified": False})

        findings = match_rules(sr, idx)
        score = readiness_score(findings)
        emit("rules", {"message": f"{len(findings)} findings, readiness {score}/100", "count": len(findings)})

        if repo.source.startswith("https://"):
            repo_name = repo.source.rstrip("/").split("/tree/")[0].split("/")[-1].removesuffix(".git")
        else:
            repo_name = repo.root.name
        report = IntegrationReport(
            repo_url=repo.source, commit_sha=repo.commit_sha, mode="M1",
            sdp_version=idx.sdp_version if idx else None, languages=sorted(sr.files.languages),
            build_systems=sr.files.build_systems, readiness_score=score, summary="",
            findings=findings, roles=sr.roles, service_name=sr.service_name,
            generated_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            sysroot_verified=idx is not None,
        )
        ctx = KitContext(repo_name=repo_name, svc=sr.service_name, arch=arch,
                         target=sr.build.executables[0] if sr.build.executables else sr.service_name,
                         main_struct=sr.main_struct, period_ms=_period_ms(sr))

        report.pillar1_features = det.build_pillar1(findings, sr, idx)
        report.pillar2_improvements = det.build_pillar2(findings, sr)
        tc_hint = generate_kit(report, ctx)[1].content.strip()            # cmake/qnx8.cmake
        report.pillar3_steps = det.build_pillar3(findings, sr, render_resmgr_excerpt(report, ctx), tc_hint)
        report.summary = det.build_summary(findings, score, sr, idx)
        emit("synth", {"message": f"{len(report.pillar1_features)} features, {len(report.pillar2_improvements)} "
                                  f"improvements, {len(report.pillar3_steps)} steps (deterministic)"})

        if use_llm:
            from .synth.llm import enrich, get_provider
            provider = get_provider()
            if provider is None:
                msg = "LLM requested but no provider key configured; deterministic report only"
            else:
                report, msg = enrich(report, sr, idx, provider, ruleset_hash())
            messages.append(msg)
            emit("guard", {"message": msg, "removed": report.unverified_claims_removed})
        else:
            emit("guard", {"message": "deterministic mode: no LLM output to guard", "removed": 0})

        report.kit = generate_kit(report, ctx)
        emit("kit", {"message": f"{len(report.kit)} kit files generated", "files": [k.path for k in report.kit]})

        if compile_kit_files and env.sdp is not None:
            from .verify.compile import check_step_snippet, compile_kit
            archs = [a for a in ("x86_64", "aarch64le") if a in env.sdp.archs()]
            results = compile_kit(report.kit, env.sdp, archs)
            ok = sum(r.ok for r in results)
            emit("qcc", {"message": f"qcc: {ok}/{len(results)} kit compilations succeeded",
                         "results": [{"ok": r.ok, "arch": r.arch, "output": r.output[-1500:]} for r in results]})
            with tempfile.TemporaryDirectory(prefix="qnx-advisor-inc-") as tmp:
                write_kit(report.kit, Path(tmp))
                for st in report.pillar3_steps:
                    st.qcc_syntax_check = check_step_snippet(  # type: ignore[assignment]
                        st, env.sdp, Path(tmp) / "include", archs[0] if archs else "x86_64")
        else:
            emit("qcc", {"message": "qcc compile check skipped (no SDP found)"})
        return AnalysisResult(report=report, scan=sr, repo=repo, kit_ctx=ctx, messages=messages)
    finally:
        if not keep_repo:
            repo.cleanup()
