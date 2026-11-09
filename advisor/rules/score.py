"""Deterministic readiness score (spec 7.1). Never produced by an LLM."""
from __future__ import annotations

from ..models import Finding

WEIGHTS = {"blocker": 15, "high": 6, "medium": 2, "low": 1, "info": 0}
CAP_PER_RULE = 3
FORMULA = "score = max(0, 100 - sum(weight(severity) x min(hits, 3))); blocker 15, high 6, medium 2, low 1; guarded findings weigh 0"


def readiness_score(findings: list[Finding]) -> int:
    total = 0
    for f in findings:
        if f.already_guarded:
            continue
        total += WEIGHTS[f.severity] * min(len(f.locations), CAP_PER_RULE)
    return max(0, 100 - total)
