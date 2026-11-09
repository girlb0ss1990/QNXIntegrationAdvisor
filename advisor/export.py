"""Report exports: Markdown (also used by the static M0 viewer) and SARIF 2.1.0."""
from __future__ import annotations

from .models import IntegrationReport
from .rules import load_rules
from .rules.score import FORMULA

SARIF_LEVEL = {"blocker": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}


def to_markdown(r: IntegrationReport) -> str:
    L = [f"# QNX 8.0 Integration Report: {r.repo_url}", "",
         f"Commit `{r.commit_sha[:12]}` · mode {r.mode} · SDP {r.sdp_version or 'not found (unverified)'} · "
         f"generated {r.generated_at_utc}", "",
         f"**Readiness score: {r.readiness_score}/100** ({FORMULA})", "", r.summary, "",
         "## Compatibility audit", "", "| Severity | Rule | Sysroot | Locations | Guidance |", "| :--- | :--- | :--- | :--- | :--- |"]
    for f in r.findings:
        locs = ", ".join(f"`{l.file_path}:{l.line_start}`" for l in f.locations[:4])
        extra = f" (link: {', '.join('-l' + x for x in f.link_libs)})" if f.link_libs else ""
        L.append(f"| {f.severity} | {f.rule_id} {f.title} | {f.sysroot_status} | {locs} | {f.guidance}{extra} |")
    L += ["", "## Pillar 1: Relevant QNX features", ""]
    for p in r.pillar1_features:
        L += [f"### {p.feature.replace('_', ' ')} (relevance {p.relevance}/5){' ✓ sysroot' if p.verified_in_sysroot else ''}",
              "", f"Component: `{p.target_component}`", "", p.rationale, ""]
        if p.apis:
            L += ["APIs: " + ", ".join(f"`{a}`" for a in p.apis), ""]
        if p.diagram_mermaid:
            L += ["```mermaid", p.diagram_mermaid, "```", ""]
    L += ["## Pillar 2: Concrete improvements", ""]
    for i in r.pillar2_improvements:
        locs = ", ".join(f"`{l.file_path}:{l.line_start}`" for l in i.evidence_locations[:3])
        L += [f"- **{i.dimension.replace('_', ' ')}** [{i.evidence_type}] {i.current_limitation} → {i.qnx_improvement}"
              + (f" ({locs})" if locs else "")]
    L += ["", "## Pillar 3: Step-by-step guidance", ""]
    for s in r.pillar3_steps:
        L += [f"### {s.n}. {s.title}", "", f"*{s.category} · effort {s.est_effort} · qcc snippet check: {s.qcc_syntax_check}*",
              "", s.explanation, ""]
        if s.before_code:
            L += ["Before:", "", "```c", s.before_code, "```", ""]
        if s.after_code:
            L += ["After:", "", "```c", s.after_code, "```", ""]
        L += ["Verify: `" + s.verify_command + "`", ""]
    if r.verification:
        L += ["## Verification records", ""]
        for v in r.verification:
            L += [f"- `{v.id}` {v.target_kind} {v.note} · SDP {v.sdp_version} · exit {v.exit_status} · sha256 `{v.binary_sha256[:16]}…`"]
            L += [f"  - {k}: {val:g}" for k, val in sorted(v.metrics.items())]
    L += ["", f"Unverified claims removed by the guard: {r.unverified_claims_removed}", ""]
    return "\n".join(L)


def to_sarif(r: IntegrationReport) -> dict:
    rules = {x.id: x for x in load_rules()}
    used = sorted({f.rule_id for f in r.findings})
    results = []
    for f in r.findings:
        for loc in f.locations:
            results.append({
                "ruleId": f.rule_id, "level": SARIF_LEVEL[f.severity],
                "message": {"text": f"{f.title}: {f.guidance}" + (" (unverified against sysroot)" if f.sysroot_status == "unknown_no_sdp" else "")},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": loc.file_path},
                                                    "region": {"startLine": loc.line_start, "endLine": loc.line_end}}}],
            })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
        "runs": [{"tool": {"driver": {
            "name": "qnx-integration-advisor", "informationUri": "https://github.com/",
            "rules": [{"id": u, "name": u, "shortDescription": {"text": rules[u].title},
                       "fullDescription": {"text": " ".join(rules[u].raw.get('guidance', '').split())}} for u in used],
        }}, "results": results}],
    }
