"""Precision/recall of rule findings against hand-labelled expectations (spec section 9).

  python eval/score.py                       # samples only (no network)
  python eval/score.py --corpus eval/corpus.yaml   # also pinned public repos (clones them)
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from advisor.pipeline import Environment, analyze  # noqa: E402


def evaluate(entries: dict[str, list[str]], sources: dict[str, tuple[str, str | None]]) -> dict:
    env = Environment(sdp=None, index=None)            # rule logic only: reproducible without an SDP
    per_rule = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    rows = []
    for name, expected in entries.items():
        if name not in sources:
            continue
        src, ref = sources[name]
        got = {f.rule_id for f in analyze(src, ref=ref, env=env, compile_kit_files=False).report.findings}
        exp = set(expected)
        for r in got & exp:
            per_rule[r]["tp"] += 1
        for r in got - exp:
            per_rule[r]["fp"] += 1
        for r in exp - got:
            per_rule[r]["fn"] += 1
        rows.append((name, sorted(got - exp), sorted(exp - got)))
    tp = sum(v["tp"] for v in per_rule.values())
    fp = sum(v["fp"] for v in per_rule.values())
    fn = sum(v["fn"] for v in per_rule.values())
    return {
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "per_rule": dict(per_rule), "rows": rows, "tp": tp, "fp": fp, "fn": fn,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", help="corpus.yaml with pinned public repositories")
    args = ap.parse_args()
    golden = yaml.safe_load((REPO / "eval" / "golden.yaml").read_text(encoding="utf-8"))
    sources = {k: (str(REPO / k), None) for k in golden if k.startswith("samples/")}
    if args.corpus:
        for e in yaml.safe_load(Path(args.corpus).read_text(encoding="utf-8")) or []:
            if e.get("commit") and e["url"] in golden:
                sources[e["url"]] = (e["url"], e["commit"])
    res = evaluate(golden, sources)
    print(f"{'rule':22s} {'tp':>3s} {'fp':>3s} {'fn':>3s}  precision  recall")
    for rule, v in sorted(res["per_rule"].items()):
        p = v["tp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else 1.0
        r = v["tp"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else 1.0
        print(f"{rule:22s} {v['tp']:3d} {v['fp']:3d} {v['fn']:3d}  {p:9.2f}  {r:6.2f}")
    for name, fps, fns in res["rows"]:
        if fps or fns:
            print(f"  {name}: false positives {fps}, missed {fns}")
    print(f"\nOVERALL precision {res['precision']:.2f} recall {res['recall']:.2f} "
          f"(tp {res['tp']}, fp {res['fp']}, fn {res['fn']}) over {len(res['rows'])} repositories")
    return 0 if res["precision"] >= 0.9 and res["recall"] >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
