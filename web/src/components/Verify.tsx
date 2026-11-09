import { useState } from "react";
import { startVerify, subscribe } from "../api";
import type { EnvInfo, IntegrationReport, JobEvent, VerificationRecord } from "../types";

function Histogram({ hist, title }: { hist: number[]; title: string }) {
  const last = Math.max(0, ...hist.map((v, i) => (v ? i : 0)));
  const shown = hist.slice(0, Math.max(last + 1, 6));
  const max = Math.max(1, ...shown);
  const label = (i: number) => (i === 0 ? "<1" : `${2 ** (i - 1)}`);
  return (
    <figure className="hist">
      <figcaption>{title}</figcaption>
      <div className="hist-bars">
        {shown.map((v, i) => (
          <div key={i} className="hist-col" title={`${v} wake-ups in [${label(i)}, ${2 ** i}) µs`}>
            <div className="hist-bar" style={{ height: `${v ? Math.max(3, (Math.log10(v + 1) / Math.log10(max + 1)) * 100) : 0}%` }} />
            <span>{label(i)}</span>
          </div>
        ))}
      </div>
      <div className="small muted">lateness bucket (µs, log₂), bar height log scale</div>
    </figure>
  );
}

function RecordView({ rec }: { rec: VerificationRecord }) {
  return (
    <div className="record">
      <h3>Verification record <code>{rec.id}</code></h3>
      <div className="meta">
        <span>{rec.target_kind}</span>{rec.note && <span className="warn">{rec.note}</span>}
        <span>SDP {rec.sdp_version}</span><span>exit {rec.exit_status}</span>
        <span title={rec.binary_sha256}>sha256 {rec.binary_sha256.slice(0, 16)}…</span>
        <span>{rec.timestamp_utc}</span>
      </div>
      <div className="small muted">{rec.target_uname}</div>
      <table className="metrics"><tbody>
        {Object.entries(rec.metrics).sort().map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}
      </tbody></table>
      <p className="small muted">Not cryptographically signed: a record of what was measured, on which binary and target.</p>
    </div>
  );
}

export function VerifyTab({ r, jobId, env, onUpdated }:
  { r: IntegrationReport; jobId: string | null; env: EnvInfo | null; onUpdated: () => void }) {
  const [target, setTarget] = useState(env?.target?.spec ?? "qnxuser@");
  const [arch, setArch] = useState("x86_64");
  const [log, setLog] = useState<JobEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const timers = log.filter((e) => e.event === "bench" && Array.isArray(e.data.hist_us_log2));

  const canRun = !!jobId && !!env?.sdp;
  const go = async () => {
    if (!jobId) return;
    setErr(null); setLog([]); setRunning(true);
    try {
      const since = await startVerify(jobId, target, arch);
      subscribe(jobId, since, (e) => {
        setLog((l) => [...l, e]);
        if (e.event === "verify_done" || e.event === "verify_error") {
          setRunning(false);
          if (e.event === "verify_error") setErr(String(e.data.message));
          onUpdated();
        }
      });
    } catch (e) { setErr(String(e)); setRunning(false); }
  };

  return (
    <div className="verify">
      {!canRun && (
        <div className="notice">
          Live verification (mode M3) needs a local QNX SDP 8.0 and a reachable QNX 8.0 target running
          <code>qnx-advisor-agent</code> (see <code>qnx-target/vm/setup-vm.sh</code>).
          {!jobId && " Sample reports are read-only."}
        </div>
      )}
      {canRun && (
        <div className="verify-form">
          <label>Target <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="qnxuser@10.0.2.15" /></label>
          <label>Arch <select value={arch} onChange={(e) => setArch(e.target.value)}>
            <option value="x86_64">x86_64 (QEMU)</option><option value="aarch64le">aarch64le (RPi 5)</option></select></label>
          <button className="btn primary" disabled={running} onClick={go}>{running ? "Verifying…" : "Verify on QNX 8.0"}</button>
        </div>
      )}
      {err && <div className="error">{err}</div>}
      {log.length > 0 && (
        <div className="terminal">
          {log.map((e, i) => (
            <div key={i} className={`ev ev-${e.event}`}>
              <span className="ev-name">{e.event}</span>
              {e.data.message ? String(e.data.message) : JSON.stringify(e.data).slice(0, 400)}
              {Array.isArray(e.data.diagnostics) && (e.data.diagnostics as { file: string; line: number; severity: string; message: string }[])
                .map((d, j) => <div key={j} className="diag">{d.file}:{d.line}: {d.severity}: {d.message}</div>)}
            </div>
          ))}
        </div>
      )}
      {timers.length > 0 && (
        <div className="hists">
          {timers.map((t, i) => <Histogram key={i} hist={t.data.hist_us_log2 as number[]}
            title={`1 kHz timer, ${String(t.data.label)} (${t.data.load_threads} burner threads): p99 ${t.data.p99_us} µs, max ${t.data.max_us} µs`} />)}
        </div>
      )}
      {r.verification.map((rec) => <RecordView key={rec.id} rec={rec} />)}
      {!r.verification.length && !log.length && <p className="muted">No verification records yet.</p>}
    </div>
  );
}
