import { useCallback, useEffect, useState } from "react";
import { STATIC_VIEWER, createJob, getEnv, getReport, getSample, listSamples, subscribe, type SampleRef } from "./api";
import { AuditTab, KitTab, PillarsTab, Summary } from "./components/Report";
import { SetupPage } from "./components/Setup";
import { VerifyTab } from "./components/Verify";
import type { EnvInfo, IntegrationReport, JobEvent } from "./types";

const STAGES = ["clone", "scan", "sysroot", "rules", "synth", "guard", "kit", "qcc"];
type Tab = "audit" | "pillars" | "kit" | "verify";

const MODE_NAME: Record<string, string> = {
  M0: "Sample viewer", M1: "Standard analysis", M2: "AI-assisted available", M3: "Live QNX target connected",
};

function Header({ env, onSetup, inSetup }: { env: EnvInfo | null; onSetup: () => void; inSetup: boolean }) {
  return (
    <header className="top">
      <div className="brand"><span className="logo">✚</span> QNX Integration Advisor</div>
      <div className="top-right">
        {env && (
          <div className="mode" title={env.mode_reason}>
            <span className={`mode-pill mode-${env.mode}`}>{env.mode}</span>
            <span className="mode-reason">{MODE_NAME[env.mode] ?? ""}
              {env.mode !== "M0" && <> · AI {env.llm ? "on" : "off"} · QNX SDP {env.sdp ? "found" : "not found"}</>}</span>
          </div>
        )}
        {!STATIC_VIEWER && (
          <button className={inSetup ? "btn setup-btn on" : "btn setup-btn"} onClick={onSetup} aria-pressed={inSetup}>⚙ Setup</button>
        )}
      </div>
    </header>
  );
}

const WELCOME_KEY = "qnx-advisor-welcome-dismissed";
function readDismissed(): boolean {
  try { return localStorage.getItem(WELCOME_KEY) === "1"; } catch { return false; }
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
  const [view, setView] = useState<"analyze" | "setup">("analyze");
  const [welcomeDismissed, setWelcomeDismissed] = useState(readDismissed);

  const loadEnv = useCallback(() => {
    getEnv().then((e) => { setEnv(e); if (!e.llm) setUseLlm(false); })
      .catch((e) => setError(`Cannot reach the local server: ${e}`));
  }, []);
  const dismissWelcome = () => {
    setWelcomeDismissed(true);
    try { localStorage.setItem(WELCOME_KEY, "1"); } catch { /* storage unavailable */ }
  };

  useEffect(() => {
    loadEnv();
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
      <Header env={env} inSetup={view === "setup"} onSetup={() => setView(view === "setup" ? "analyze" : "setup")} />
      <main>
        {view === "setup" && <SetupPage onChanged={loadEnv} onClose={() => setView("analyze")} />}
        {view === "analyze" && <>
        {!STATIC_VIEWER && !welcomeDismissed && env && (
          <div className="welcome">
            <div>
              <strong>Welcome!</strong> Paste a link to a C or C++ project on GitHub (or a folder on this computer) and
              press <strong>Analyze</strong> to see what it needs to run on QNX 8.0. Or open a sample report below.
              {" "}Open <button className="link inline" onClick={() => setView("setup")}>Setup</button> to check
              everything is connected and to turn on the optional AI assistant.
            </div>
            <button className="close" onClick={dismissWelcome} aria-label="Dismiss welcome message">×</button>
          </div>
        )}
        {!STATIC_VIEWER && (
          <section className="new-scan">
            <input className="source" value={source} onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && source.trim() && start()}
              placeholder="https://github.com/owner/repo  or  /path/to/local/checkout" />
            <select value={arch} onChange={(e) => setArch(e.target.value)} aria-label="target architecture">
              <option value="x86_64">x86_64</option><option value="aarch64le">aarch64le</option>
            </select>
            {env?.llm ? (
              <label className="check" title={`Uses ${env.llm}. Billed by your AI provider.`}>
                <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> AI-assisted
              </label>
            ) : (
              <button className="link ai-off" onClick={() => setView("setup")} title="The AI assistant is optional">
                Turn on AI…</button>
            )}
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
        </>}
      </main>
      <footer>Local-first: QNX SDP content stays on this machine. Apache-2.0.</footer>
    </div>
  );
}
