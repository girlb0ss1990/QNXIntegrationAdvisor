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

function Outcome({ rec, svc }: { rec: VerificationRecord; svc: string }) {
  const m = rec.metrics;
  const appeared = (m.verify_path_appeared ?? (m.resmgr_ready_ms !== undefined ? 1 : 0)) > 0;
  const items: [boolean, string][] = [
    [true, `Compiled with QNX qcc (SDP ${rec.sdp_version}) and copied to the target`],
    [true, `Ran on ${rec.target_uname.split(" ").slice(0, 3).join(" ")} (${rec.target_kind.replace("_", " ")})`],
    [appeared, appeared ? `Your service registered /dev/${svc}` +
      (m.resmgr_ready_ms !== undefined ? ` ${m.resmgr_ready_ms} ms after start` : "") + ", then the agent stopped it as planned"
      : `/dev/${svc} did not appear`],
  ];
  if (m.compat_selftest_exit !== undefined) items.push([m.compat_selftest_exit === 0, m.compat_selftest_exit === 0
    ? "The compatibility self-test passed on QNX" : `The compatibility self-test failed (exit ${m.compat_selftest_exit})`]);
  if (m.ipc_rtt_p50_ns !== undefined) items.push([true, `Measured QNX message passing: median round trip ${(m.ipc_rtt_p50_ns / 1000).toFixed(1)} µs`]);
  if (m.timer_late_p99_us_loaded !== undefined) items.push([true, `Measured a 1 kHz real-time timer under CPU load: 99% of wake-ups within ${Math.round(m.timer_late_p99_us_loaded)} µs of the deadline`]);
  return (
    <ul className="outcome">
      {items.map(([ok, t], i) => <li key={i} className={ok ? "ok" : "bad"}><span>{ok ? "✓" : "✕"}</span> {t}</li>)}
    </ul>
  );
}

function RecordView({ rec, svc }: { rec: VerificationRecord; svc: string }) {
  return (
    <div className="record">
      <h3>Verification record <code>{rec.id}</code></h3>
      <Outcome rec={rec} svc={svc} />
      <div className="meta">
        <span>{rec.target_kind}</span>{rec.note && <span className="warn">{rec.note}</span>}
        <span>SDP {rec.sdp_version}</span>
        <span title="-1 means the service was still running and the agent stopped it with a signal, as designed">exit {rec.exit_status}</span>
        <span title={rec.binary_sha256}>sha256 {rec.binary_sha256.slice(0, 16)}…</span>
        <span>{rec.timestamp_utc}</span>
      </div>
      <div className="small muted">{rec.target_uname}</div>
      <table className="metrics"><tbody>
        {Object.entries(rec.metrics).sort().map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}
      </tbody></table>
      <p className="small muted">Not cryptographically signed: a record of what was measured, on which binary and target.
        QEMU timings depend on your PC and are indicative only; measure on real hardware before relying on them.</p>
    </div>
  );
}

export function VerifyTab({ r, jobId, env, onUpdated, onOpenSetup }:
  { r: IntegrationReport; jobId: string | null; env: EnvInfo | null; onUpdated: () => void; onOpenSetup?: () => void }) {
  const [target, setTarget] = useState(env?.target?.spec ?? "qnxuser@");
  const targetUp = !!env?.target?.reachable;
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
      <div className="notice">
        <strong>Run it on real QNX.</strong> One click builds the generated QNX code with <code>qcc</code>, copies it to
        a QNX 8.0 target (the built-in QEMU virtual machine is fine), starts your service there, checks that
        <code>/dev/{r.service_name}</code> appears, runs the compatibility self-test, and measures QNX message passing
        and real-time timer accuracy.
        {!jobId && <div className="muted">Sample reports are read-only: analyze a repository (or a sample folder) to run this.</div>}
        {jobId && !env?.sdp && <div className="muted">Needs the QNX SDP. On Windows, start the advisor with
          start.bat and answer Y to <em>QNX mode</em>.</div>}
        {jobId && env?.sdp && !targetUp && <div className="muted">No QNX target is running yet.{" "}
          {onOpenSetup && <button className="btn" onClick={onOpenSetup}>Open Setup → Start QNX virtual machine</button>}</div>}
      </div>
      {canRun && (
        <div className="verify-form">
          <label>Target <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="qnxuser@10.0.2.15" /></label>
          <label>Arch <select value={arch} onChange={(e) => setArch(e.target.value)}>
            <option value="x86_64">x86_64 (QEMU)</option><option value="aarch64le">aarch64le (RPi 5)</option></select></label>
          <button className="btn primary" disabled={running} onClick={go}>{running ? "Running on QNX…" : "Run on QNX 8.0"}</button>
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
      {r.verification.slice().reverse().map((rec) => <RecordView key={rec.id} rec={rec} svc={r.service_name} />)}
      {!r.verification.length && !log.length && <p className="muted">No verification records yet.</p>}
    </div>
  );
}
