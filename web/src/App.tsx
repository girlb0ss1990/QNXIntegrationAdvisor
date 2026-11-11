import { useCallback, useEffect, useState } from "react";
import { STATIC_VIEWER, createJob, getEnv, getReport, getSample, listSamples, subscribe, type SampleRef } from "./api";
import { AuditTab, KitTab, PillarsTab, Summary } from "./components/Report";
import { VerifyTab } from "./components/Verify";
import type { EnvInfo, IntegrationReport, JobEvent } from "./types";

const STAGES = ["clone", "scan", "sysroot", "rules", "synth", "guard", "kit", "qcc"];
type Tab = "audit" | "pillars" | "kit" | "verify";

function Header({ env }: { env: EnvInfo | null }) {
  return (
    <header className="top">
      <div className="brand"><span className="logo">✚</span> QNX Integration Advisor</div>
      {env && (
        <div className="mode" title={env.mode_reason}>
          <span className={`mode-pill mode-${env.mode}`}>{env.mode}</span>
          <span className="mode-reason">{env.mode_reason}</span>
        </div>
      )}
    </header>
  );
}

function Progress({ events }: { events: JobEvent[] }) {
  const seen = new Set(events.map((e) => e.event));
  const last = events[events.length - 1];
  return (
    <div className="progress">
      <ol className="stages">
        {STAGES.map((s) => <li key={s} className={seen.has(s) ? "done" : ""}>{s}</li>)}
      </ol>
      <div className="terminal small">
        {events.map((e, i) => <div key={i} className={`ev ev-${e.event}`}><span className="ev-name">{e.event}</span>{String(e.data.message ?? "")}</div>)}
      </div>
      {last?.event === "error" && <div className="error">{String(last.data.message)}</div>}
    </div>
  );
}

export default function App() {
  const [env, setEnv] = useState<EnvInfo | null>(null);
  const [samples, setSamples] = useState<SampleRef[]>([]);
  const [source, setSource] = useState("");
  const [arch, setArch] = useState("x86_64");
  const [useLlm, setUseLlm] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [report, setReport] = useState<IntegrationReport | null>(null);
  const [tab, setTab] = useState<Tab>("audit");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getEnv().then(setEnv).catch((e) => setError(`Cannot reach the local server: ${e}`));
    listSamples().then(setSamples).catch(() => setSamples([]));
  }, []);

  const start = async () => {
    setError(null); setReport(null); setEvents([]);
    try {
      const id = await createJob({ source: source.trim(), arch, use_llm: useLlm });
      setJobId(id);
      subscribe(id, 0, (e) => {
        setEvents((ev) => [...ev, e]);
        if (e.event === "done") getReport(id).then((r) => { setReport(r); setTab("audit"); });
      });
    } catch (e) { setError(String(e)); }
  };

  const refresh = useCallback(() => { if (jobId) getReport(jobId).then(setReport); }, [jobId]);
  const openSample = async (s: SampleRef) => {
    setError(null); setJobId(null); setEvents([]);
    try { setReport(await getSample(s)); setTab("audit"); } catch (e) { setError(String(e)); }
  };
  const running = events.length > 0 && !events.some((e) => e.event === "done" || e.event === "error");

  return (
    <div className="app">
      <Header env={env} />
      <main>
        {!STATIC_VIEWER && (
          <section className="new-scan">
            <input className="source" value={source} onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && source.trim() && start()}
              placeholder="https://github.com/owner/repo  or  /path/to/local/checkout" />
            <select value={arch} onChange={(e) => setArch(e.target.value)} aria-label="target architecture">
              <option value="x86_64">x86_64</option><option value="aarch64le">aarch64le</option>
            </select>
            <label className="check" title={env?.llm ? `provider ${env.llm}` : "set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY"}>
              <input type="checkbox" checked={useLlm} disabled={!env?.llm} onChange={(e) => setUseLlm(e.target.checked)} /> AI-assisted
            </label>
            <button className="btn primary" disabled={!source.trim() || running} onClick={start}>{running ? "Analyzing…" : "Analyze"}</button>
          </section>
        )}
        <p className="hint">
          The repository is cloned and read, never built or run on this machine.
          {env && !env.sdp && " No QNX SDP found: results are labelled unverified against a sysroot."}
        </p>
        {samples.length > 0 && (
          <div className="samples">Sample reports:
            {samples.map((s) => <button key={s.name} className="link" onClick={() => openSample(s)}>{s.name}</button>)}
          </div>
        )}
        {error && <div className="error">{error}</div>}
        {events.length > 0 && !report && <Progress events={events} />}

        {report && (
          <>
            <Summary r={report} />
            {report.applicable === false ? null : (<>
            <nav className="tabs">
              {(["audit", "pillars", "kit", "verify"] as Tab[]).map((t) => (
                <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                  {{ audit: `Audit (${report.findings.length})`, pillars: "3-pillar report", kit: `Porting kit (${report.kit.length})`, verify: "Verify on QNX" }[t]}
                </button>
              ))}
              {jobId && <a className="export" href={`api/jobs/${jobId}/report.md`} target="_blank" rel="noreferrer">report.md</a>}
              {jobId && <a className="export" href={`api/jobs/${jobId}/report.sarif`} target="_blank" rel="noreferrer">SARIF</a>}
            </nav>
            {tab === "audit" && <AuditTab r={report} />}
            {tab === "pillars" && <PillarsTab r={report} />}
            {tab === "kit" && <KitTab r={report} kitUrl={jobId ? `api/jobs/${jobId}/kit.zip` : null} />}
            {tab === "verify" && <VerifyTab r={report} jobId={jobId} env={env} onUpdated={refresh} />}
            </>)}
          </>
        )}
      </main>
      <footer>Local-first: QNX SDP content stays on this machine. Apache-2.0.</footer>
    </div>
  );
}
