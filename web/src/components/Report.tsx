import { useMemo, useState } from "react";
import type { IntegrationReport, KitFile } from "../types";
import { CodeBlock, DiffView, EvidenceBadge, Inline, Loc, Mermaid, SeverityBadge, SysrootBadge } from "./common";

const SCORE_FORMULA =
  "score = max(0, 100 − Σ weight(severity) × min(hits, 3)). Weights: blocker 15, high 6, medium 2, low 1. " +
  "Findings already inside __QNX__/__linux__ guards weigh 0. Deterministic, never produced by an LLM.";

export function Summary({ r }: { r: IntegrationReport }) {
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    r.findings.forEach((f) => { c[f.severity] = (c[f.severity] ?? 0) + 1; });
    return c;
  }, [r]);
  const na = r.applicable === false || r.readiness_score === null;
  return (
    <section className={na ? "summary not-applicable" : "summary"}>
      {na ? (
        <div className="score" title="No C/C++ sources: this tool analyses C/C++ code, so no score is given.">
          <div className="score-num">N/A</div>
          <div className="score-label">not applicable</div>
        </div>
      ) : (
        <div className="score" title={SCORE_FORMULA}>
          <div className="score-num">{r.readiness_score}</div>
          <div className="score-label">readiness / 100 <span className="info-dot">ⓘ</span></div>
        </div>
      )}
      <div className="summary-body">
        <h2>{r.repo_url}</h2>
        <div className="meta">
          <span>commit <code>{r.commit_sha.slice(0, 12)}</code></span>
          <span>{r.languages.join(", ") || "no recognised source files"}</span>
          <span>{r.build_systems.join(", ") || "no build system"}</span>
          {!na && <span>service <code>{r.service_name}</code></span>}
          <span className={r.sysroot_verified ? "ok" : "warn"}>
            {r.sysroot_verified ? `verified against SDP ${r.sdp_version} sysroot` : "unverified against sysroot"}
          </span>
        </div>
        <p><Inline text={r.summary} /></p>
        <div className="sevbar">
          {(["blocker", "high", "medium", "low", "info"] as const).map((s) =>
            counts[s] ? <span key={s}><SeverityBadge s={s} /> {counts[s]}</span> : null)}
          {r.unverified_claims_removed > 0 &&
            <span className="guard-count" title="API names, headers or numeric claims removed by the hallucination guard">
              {r.unverified_claims_removed} unverified claim(s) removed</span>}
        </div>
      </div>
    </section>
  );
}

export function AuditTab({ r }: { r: IntegrationReport }) {
  const [open, setOpen] = useState<string | null>(r.findings[0]?.rule_id ?? null);
  if (!r.findings.length) return <p className="muted">No Linux-specific patterns found.</p>;
  return (
    <div className="findings">
      {r.findings.map((f) => (
        <div key={f.rule_id} className={`finding ${open === f.rule_id ? "open" : ""}`}>
          <button className="finding-head" onClick={() => setOpen(open === f.rule_id ? null : f.rule_id)}>
            <SeverityBadge s={f.severity} />
            <span className="rule">{f.rule_id}</span>
            <span className="title">{f.title}</span>
            <SysrootBadge status={f.sysroot_status} />
            {f.link_libs.length > 0 && <span className="badge lib">link {f.link_libs.map((l) => "-l" + l).join(" ")}</span>}
            {f.already_guarded && <span className="badge guarded">already guarded</span>}
            <span className="count">{f.locations.length} hit{f.locations.length === 1 ? "" : "s"}</span>
          </button>
          {open === f.rule_id && (
            <div className="finding-body">
              <p><Inline text={f.guidance} /></p>
              {f.sysroot_detail && <p className="detail">Sysroot check: {f.sysroot_detail}</p>}
              {f.alternatives.length > 0 && (
                <div className="alts">
                  {f.alternatives.map((a, i) => (
                    <div key={i} className="alt">
                      <span className="badge kind">{a.kind.replace("_", " ")}</span>
                      {a.apis.map((x) => <code key={x}>{x}</code>)}
                      <span className="muted">{a.note}</span>
                    </div>
                  ))}
                </div>
              )}
              <table className="locs">
                <tbody>
                  {f.locations.map((l) => (
                    <tr key={l.file_path + l.line_start}><td><Loc l={l} /></td><td><code className="snip">{l.snippet}</code></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function PillarsTab({ r }: { r: IntegrationReport }) {
  const [pillar, setPillar] = useState<1 | 2 | 3>(1);
  const [step, setStep] = useState(1);
  const current = r.pillar3_steps.find((s) => s.n === step) ?? r.pillar3_steps[0];
  return (
    <div>
      <div className="subtabs">
        <button className={pillar === 1 ? "on" : ""} onClick={() => setPillar(1)}>1 · QNX features &amp; why</button>
        <button className={pillar === 2 ? "on" : ""} onClick={() => setPillar(2)}>2 · Improvements for this repo</button>
        <button className={pillar === 3 ? "on" : ""} onClick={() => setPillar(3)}>3 · Step-by-step guidance</button>
      </div>

      {pillar === 1 && (
        <div className="cards">
          {r.pillar1_features.map((f) => (
            <article key={f.feature} className="card">
              <header>
                <h3>{f.feature.replace(/_/g, " ")}</h3>
                <span className="relevance" title="relevance">{"●".repeat(f.relevance)}{"○".repeat(5 - f.relevance)}</span>
              </header>
              <div className="muted small">for <code>{f.target_component}</code>
                {f.verified_in_sysroot && <span className="badge sys-available">APIs in sysroot</span>}</div>
              <p><Inline text={f.rationale} /></p>
              {f.apis.length > 0 && <div className="apis">{f.apis.map((a) => <code key={a}>{a}</code>)}</div>}
              {f.diagram_mermaid && <Mermaid code={f.diagram_mermaid} />}
            </article>
          ))}
        </div>
      )}

      {pillar === 2 && (
        <div className="improvements">
          {r.pillar2_improvements.map((i, k) => (
            <div key={k} className="improvement">
              <div className="imp-head">
                <span className="dim">{i.dimension.replace(/_/g, " ")}</span>
                <EvidenceBadge e={i.evidence_type} />
                {i.evidence_locations.slice(0, 3).map((l) => <Loc key={l.file_path + l.line_start} l={l} />)}
              </div>
              <div className="imp-grid">
                <div><div className="label">Today</div><p><Inline text={i.current_limitation} /></p></div>
                <div><div className="label">On QNX 8.0</div><p><Inline text={i.qnx_improvement} /></p></div>
              </div>
            </div>
          ))}
        </div>
      )}

      {pillar === 3 && current && (
        <div className="steps">
          <ol className="step-list">
            {r.pillar3_steps.map((s) => (
              <li key={s.n} className={s.n === current.n ? "on" : ""} onClick={() => setStep(s.n)}>
                <span className="n">{s.n}</span><span>{s.title}</span>
                <span className="effort">{s.est_effort}</span>
              </li>
            ))}
          </ol>
          <div className="step-detail">
            <h3>{current.n}. {current.title}</h3>
            <div className="meta">
              <span>{current.category.replace(/_/g, " ")}</span>
              <span>effort {current.est_effort}</span>
              <span className={`qcc-${current.qcc_syntax_check}`}>qcc snippet check: {current.qcc_syntax_check}</span>
              {current.affected_files.map((f) => <code key={f}>{f}</code>)}
            </div>
            <p><Inline text={current.explanation} /></p>
            {(current.before_code || current.after_code) && <DiffView before={current.before_code} after={current.after_code} />}
            <div className="label">Verify</div>
            <CodeBlock code={current.verify_command} lang="sh" />
          </div>
        </div>
      )}
    </div>
  );
}

const QCC_LABEL: Record<string, string> = {
  both: "qcc ✓ x86_64 + aarch64le", x86_64: "qcc ✓ x86_64", aarch64le: "qcc ✓ aarch64le",
  skipped: "qcc not run (no SDP)", not_applicable: "", failed: "qcc ✗ failed",
};

export function KitTab({ r, kitUrl }: { r: IntegrationReport; kitUrl: string | null }) {
  const [sel, setSel] = useState<KitFile | null>(r.kit[0] ?? null);
  return (
    <div className="kit">
      <div className="kit-list">
        {kitUrl && <a className="btn primary" href={kitUrl}>Download kit (.zip)</a>}
        {r.kit.map((k) => (
          <button key={k.path} className={sel?.path === k.path ? "on" : ""} onClick={() => setSel(k)}>
            <code>{k.path}</code>
            <span className="small muted">{k.description}</span>
            {QCC_LABEL[k.qcc_compiled] && <span className={`badge qcc-${k.qcc_compiled}`}>{QCC_LABEL[k.qcc_compiled]}</span>}
          </button>
        ))}
      </div>
      <div className="kit-view">{sel && <CodeBlock code={sel.content} />}</div>
    </div>
  );
}
