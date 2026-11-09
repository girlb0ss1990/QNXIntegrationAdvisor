from __future__ import annotations

import yaml

from advisor.models import Finding, SourceLocation
from advisor.rules import config_globs, interesting_tokens, load_features, load_rules
from advisor.rules.matcher import match_rules
from advisor.rules.score import readiness_score
from advisor.rules.validate import validate
from advisor.scanner import scan_repo
from conftest import REPO, SAMPLES


def _findings(name, idx=None):
    sr = scan_repo(SAMPLES / name, interesting_tokens(), config_globs())
    return {f.rule_id: f for f in match_rules(sr, idx)}


def test_rule_db_is_well_formed():
    rules = load_rules()
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids)) >= 18
    features = load_features()
    for r in rules:
        assert r.raw.get("guidance"), r.id
        for tag in r.feature_tags:
            assert tag in features, (r.id, tag)
        if r.availability is not None:
            assert {"severity_if_missing", "severity_if_available", "expected_on_qnx"} <= r.raw.keys(), r.id
        else:
            assert "severity" in r.raw, r.id


def test_no_aps_anywhere():
    """Spec E1: APS was discontinued in SDP 8.0 and must never be recommended."""
    text = (REPO / "advisor" / "rules" / "rules.yaml").read_text(encoding="utf-8")
    text += (REPO / "advisor" / "rules" / "features.yaml").read_text(encoding="utf-8")
    assert "SCHED_APS" not in text and "sched_aps" not in text


def test_without_sdp_everything_is_labelled_unverified():
    f = _findings("motor-pid-controller")
    assert f["LNX-EPOLL"].sysroot_status == "unknown_no_sdp"
    assert f["LNX-EPOLL"].severity == "blocker"
    assert f["LNX-INOTIFY"].severity == "low" and f["LNX-INOTIFY"].link_libs == ["fsnotify"]


def test_sysroot_decides_severity(fake_index):
    f = _findings("motor-pid-controller", fake_index)
    assert f["LNX-EPOLL"].sysroot_status == "missing" and f["LNX-EPOLL"].severity == "blocker"
    ino = f["LNX-INOTIFY"]
    assert ino.sysroot_status == "available" and ino.severity == "low" and ino.link_libs == ["fsnotify"]
    libs = f["LNX-LIBS"]
    assert libs.sysroot_status == "missing" and "libpthread" in libs.sysroot_detail


def test_libs_not_flagged_when_present_in_sysroot(fake_index):
    fake_index.libraries |= {"pthread", "rt"}
    f = _findings("motor-pid-controller", fake_index)
    assert f["LNX-LIBS"].severity == "info"


def test_socklib_maps_symbol_to_library(fake_index):
    f = _findings("can-telemetry-daemon", fake_index)
    assert f["LNX-SOCKLIB"].link_libs == ["socket"]
    fake_index.symbols["socket"] = ["c"]               # an SDP where socket() is in libc: nothing to fix
    assert "LNX-SOCKLIB" not in _findings("can-telemetry-daemon", fake_index)


def test_prio_inversion_needs_mixed_priorities():
    assert "LNX-PRIO-INV" in _findings("motor-pid-controller")
    assert "LNX-PRIO-INV" not in _findings("vitals-monitor")     # threads, but no real-time priorities


def test_golden_labels_match():
    golden = yaml.safe_load((REPO / "eval" / "golden.yaml").read_text(encoding="utf-8"))
    for name, expected in golden.items():
        got = set(_findings(name.split("/", 1)[1]))
        assert got == set(expected), name


def _f(sev, n, guarded=False):
    loc = SourceLocation(file_path="a.c", line_start=1, line_end=1)
    return Finding(rule_id="X", severity=sev, sysroot_status="missing", locations=[loc] * n, already_guarded=guarded)


def test_readiness_score_formula():
    assert readiness_score([]) == 100
    assert readiness_score([_f("blocker", 1)]) == 85
    assert readiness_score([_f("blocker", 10)]) == 55            # capped at 3 per rule
    assert readiness_score([_f("high", 2), _f("medium", 1), _f("low", 1), _f("info", 5)]) == 100 - 12 - 2 - 1
    assert readiness_score([_f("blocker", 3, guarded=True)]) == 100
    assert readiness_score([_f("blocker", 3)] * 3) == 0


def test_validate_reports_missing_apis(fake_index):
    del fake_index.symbols["ionotify"]
    fake_index.headers.discard("ha/ham.h")
    problems = validate(fake_index)
    assert any("LNX-EPOLL: 'ionotify'" in p for p in problems)
    assert any("<ha/ham.h>" in p for p in problems)
    known = {a for r in load_rules() for alt in r.alternatives for a in alt.get("apis", [])}
    known |= {a for f in load_features().values() for a in f.get("apis", [])}
    fake_index.declared |= known
    fake_index.headers |= {h for f in load_features().values() for h in f.get("headers", [])}
    assert validate(fake_index) == []
