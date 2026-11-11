from __future__ import annotations

import io
import re
import zipfile

from advisor.kit.generator import kit_zip
from advisor.pipeline import Environment, analyze
from advisor.synth.guard import Guard
from advisor.synth.llm import LLMEnrichment, LLMFeatureNote, LLMImprovement, LLMStepNote, apply_enrichment
from conftest import SAMPLES


def _analyze(name, idx=None):
    return analyze(str(SAMPLES / name), env=Environment(sdp=None, index=idx), compile_kit_files=False)


def test_report_has_three_pillars_and_ordered_steps():
    r = _analyze("motor-pid-controller").report
    assert r.mode == "M1" and not r.sysroot_verified
    feats = {f.feature for f in r.pillar1_features}
    assert {"resource_manager", "channels_pulses", "priority_inheritance"} <= feats
    assert all(i.evidence_type in ("static", "qualitative") for i in r.pillar2_improvements)   # nothing measured yet
    cats = [s.category for s in r.pillar3_steps]
    assert cats[0] == "toolchain_build" and cats[-1] == "deploy_verify"
    assert [s.n for s in r.pillar3_steps] == list(range(1, len(cats) + 1))
    timer = next(s for s in r.pillar3_steps if "timerfd" in s.title)
    assert "timerfd_create" in timer.before_code and "qnx_periodic_timer_create" in timer.after_code


def test_no_made_up_numbers_in_deterministic_report():
    """Spec E12: no quantified performance claims unless measured."""
    for name in ("motor-pid-controller", "can-telemetry-daemon", "vitals-monitor"):
        r = _analyze(name).report
        text = " ".join([r.summary] + [f.rationale for f in r.pillar1_features]
                        + [i.current_limitation + i.qnx_improvement for i in r.pillar2_improvements])
        assert not re.search(r"\d+(\.\d+)?\s*(µs|us|ms|ns)\b|\d+\s*%", text), name


def test_kit_renders_and_is_consistent():
    r = _analyze("can-telemetry-daemon").report
    paths = {k.path: k.content for k in r.kit}
    assert "src/qnx_candaemon_resmgr.c" in paths and "src/candaemon_dcmd.h" in paths
    for p, c in paths.items():
        assert "{{" not in c and "{%" not in c, p
        if p.endswith((".c", ".h")):
            assert c.count("{") == c.count("}"), p
            assert c.count("(") == c.count(")"), p
    res = paths["src/qnx_candaemon_resmgr.c"]
    for api in ("dispatch_create", "resmgr_attach", "pulse_attach", "iofunc_devctl_default", "procmgr_ability"):
        assert api in res
    assert "qnx_notifier_signal" in paths["include/qnx_compat.h"]          # eventfd shim requested
    assert "qnx_periodic_timer_create" in paths["include/qnx_compat.h"]      # flusher thread's sleep(1) loop
    assert "-lsocket" not in paths["cmake/qnx8.cmake"] and "socket" in paths["cmake/qnx8.cmake"]
    assert "mkqnximage --type=qemu" in paths["target/run-qemu.sh"]
    z = zipfile.ZipFile(io.BytesIO(kit_zip(r.kit, "kit")))
    assert sorted(z.namelist()) == sorted(f"kit/{p}" for p in paths)


def test_guard_filters_hallucinations(fake_index):
    g = Guard(fake_index, {"pid_step"})
    assert g.filter_apis(["MsgSendPulse", "pid_step", "MsgSendTurbo"]) == ["MsgSendPulse", "pid_step"]
    assert g.filter_headers(["sys/neutrino.h", "sys/aps.h"]) == ["sys/neutrino.h"]
    text = "Use MsgSendPulse() to wake the loop. Call SchedCtl(SCHED_APS_QUERY_PARMS) too. It is 40% faster."
    assert g.filter_text(text) == "Use MsgSendPulse() to wake the loop."
    assert g.result.removed == 4
    assert g.filter_code("int x = frobnicate_qnx(1);") is None
    assert g.filter_code("static int helper(void) { return 1; }\nint y = helper();") is not None


def test_llm_enrichment_is_guarded(fake_index):
    res = _analyze("motor-pid-controller", fake_index)
    r = res.report
    e = LLMEnrichment(
        summary="The control loop in src/main.c should become a pulse-driven resource manager. It will be 10x faster.",
        features=[LLMFeatureNote(feature="channels_pulses",
                                 rationale="Replace the epoll loop with MsgReceivePulse(). Also call MagicQnxApi().",
                                 diagram_mermaid="flowchart LR\n  A[\"timer\"] --> B[\"loop\"]")],
        steps=[LLMStepNote(n=1, explanation="Use the kit toolchain file.", after_code="int z = not_an_api();")],
        extra_improvements=[
            LLMImprovement(dimension="determinism_latency", current_limitation="usleep in telemetry thread.",
                           qnx_improvement="Use clock_nanosleep() with absolute deadlines.", file_path="src/main.c", line=55),
            LLMImprovement(dimension="ipc_efficiency", current_limitation="x.", qnx_improvement="y.",
                           file_path="src/nope.c", line=3),
        ],
    )
    out = apply_enrichment(r, e, Guard(fake_index, res.scan.repo_symbols), res.scan)
    assert out.mode == "M2"
    assert "10x" not in out.summary and "pulse-driven" in out.summary
    cp = next(f for f in out.pillar1_features if f.feature == "channels_pulses")
    assert "MagicQnxApi" not in cp.rationale and "MsgReceivePulse" in cp.rationale
    assert cp.diagram_mermaid.startswith("flowchart LR")
    assert out.pillar3_steps[0].after_code != "int z = not_an_api();"
    assert any(i.evidence_locations and i.evidence_locations[0].line_start == 55 for i in out.pillar2_improvements)
    assert not any(i.evidence_locations and i.evidence_locations[0].file_path == "src/nope.c" for i in out.pillar2_improvements)
    assert out.unverified_claims_removed >= 4


def test_repo_without_c_or_cpp_is_not_applicable(tmp_path):
    """A JavaScript/TypeScript repo must not get a misleading 100/100 readiness score."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("console.log('hi');\n")
    (tmp_path / "src" / "util.ts").write_text("export const x = 1;\n")
    (tmp_path / "package.json").write_text("{}\n")
    res = analyze(str(tmp_path), env=Environment(sdp=None, index=None), compile_kit_files=False)
    r = res.report
    assert r.applicable is False
    assert r.readiness_score is None
    assert r.kit == [] and r.findings == [] and r.pillar3_steps == []
    assert r.languages == ["JavaScript", "TypeScript"]
    assert "Not applicable" in r.summary
    from advisor.export import to_markdown
    assert "not applicable" in to_markdown(r)
