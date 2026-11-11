import { useEffect, useState } from "react";
import { clearLlm, getSetup, importWslIndex, saveLlm, testLlm } from "../api";
import type { LlmTest, SetupCheck, SetupInfo } from "../types";

const ICON: Record<SetupCheck["status"], string> = { ok: "✓", warn: "!", missing: "✕", optional: "○" };
const STATUS_TEXT: Record<SetupCheck["status"], string> = {
  ok: "Ready", warn: "Needs attention", missing: "Not working", optional: "Optional · not set up",
};

function Checklist({ checks, onAction, actionBusy, actionMsg }: {
  checks: SetupCheck[]; onAction: (a: string) => void; actionBusy: boolean; actionMsg: string | null;
}) {
  return (
    <ul className="checklist">
      {checks.map((c) => (
        <li key={c.id} className={`check-row st-${c.status}`}>
          <span className="check-icon" aria-hidden>{ICON[c.status]}</span>
          <div className="check-body">
            <div className="check-title">
              <strong>{c.label}</strong>
              <span className="check-state">{STATUS_TEXT[c.status]}</span>
            </div>
            <div className="check-detail">{c.detail}</div>
            {c.fix && <div className="check-fix"><span className="label-inline">How to fix:</span> {c.fix}</div>}
            {c.action === "import_wsl_index" && (
              <div className="row-gap">
                <button className="btn primary" disabled={actionBusy} onClick={() => onAction(c.action!)}>
                  {actionBusy ? "Importing…" : "Use my WSL QNX SDP"}</button>
              </div>
            )}
            {c.id === "sdp" && actionMsg && <div className="error">{actionMsg}</div>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function TestResult({ t }: { t: LlmTest | null }) {
  if (!t) return null;
  return (
    <div className={t.ok ? "test-result ok-box" : "test-result bad-box"} role="status">
      <strong>{t.ok ? "✓ Connected" : "✕ Not connected"}</strong> {t.message}
      {t.ok && t.latency_ms !== undefined && <span className="muted small"> ({(t.latency_ms / 1000).toFixed(1)} s)</span>}
    </div>
  );
}

export function SetupPage({ onChanged, onClose }: { onChanged: () => void; onClose: () => void }) {
  const [info, setInfo] = useState<SetupInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [provider, setProvider] = useState("openrouter");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "test" | "remove">("");
  const [formError, setFormError] = useState<string | null>(null);
  const [test, setTest] = useState<LlmTest | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const reload = async () => {
    try {
      const s = await getSetup();
      setInfo(s);
      setLoadError(null);
      if (s.llm.active) {
        setProvider(s.llm.active.provider);
        setTest(s.llm.active.last_test);
        if (s.llm.active.model !== s.llm.active.default_model) setModel(s.llm.active.model);
      }
    } catch (e) { setLoadError(String(e)); }
  };
  useEffect(() => { reload(); }, []);

  const active = info?.llm.active ?? null;
  const p = info?.llm.providers.find((x) => x.id === provider);
  const keyLooksOff = !!(apiKey && p && !apiKey.trim().startsWith(p.key_hint));
  const sameProviderSaved = active?.provider === provider && active.source === "settings";

  const runTest = async () => {
    setBusy("test"); setTest(null);
    try { setTest(await testLlm()); } catch (e) { setTest({ ok: false, message: String(e) }); }
    setBusy(""); await reload(); onChanged();
  };

  const save = async () => {
    setFormError(null); setBusy("save");
    try {
      await saveLlm({ provider, api_key: apiKey.trim() || undefined, model: model.trim() || undefined });
      setApiKey(""); setShowKey(false);
      setBusy("");
      await runTest();
    } catch (e) {
      setFormError(String(e).replace(/^Error: \d+: /, ""));
      setBusy("");
    }
  };

  const runAction = async (a: string) => {
    if (a !== "import_wsl_index") return;
    setActionBusy(true); setActionMsg(null);
    try { await importWslIndex(); } catch (e) { setActionMsg(String(e).replace(/^Error: \d+: /, "")); }
    setActionBusy(false); await reload(); onChanged();
  };

  const remove = async () => {
    setBusy("remove");
    try { await clearLlm(); setTest(null); setModel(""); } catch (e) { setFormError(String(e)); }
    setBusy(""); await reload(); onChanged();
  };

  return (
    <section className="setup">
      <div className="setup-head">
        <div>
          <h2>Setup</h2>
          <p className="muted">Check that everything is connected. Only <strong>Git</strong> and the
            <strong> code parser</strong> are needed; everything marked optional adds extra features.</p>
        </div>
        <div className="setup-actions">
          <button className="btn" onClick={reload}>Check again</button>
          <button className="btn primary" onClick={onClose}>Back to analysis</button>
        </div>
      </div>

      {loadError && <div className="error">Could not load the setup status: {loadError}</div>}
      {info ? <Checklist checks={info.checks} onAction={runAction} actionBusy={actionBusy} actionMsg={actionMsg} /> : !loadError && <p className="muted">Checking…</p>}

      <div className="ai-card">
        <h3>AI assistant <span className="badge">optional</span></h3>
        <p>
          AI rewrites the explanations for the repository you analyse and adds diagrams. Reports are complete
          without it. Every AI answer is fact-checked: QNX functions that do not exist and invented performance
          numbers are removed. <strong>Your key is stored only on this computer</strong> and is sent only to the
          provider you choose. Each AI-assisted analysis is billed by that provider.
        </p>

        {active && (
          <div className="active-ai">
            <div><span className="label-inline">Active:</span> <strong>{active.label}</strong> · model <code>{active.model}</code> · key <code>{active.key_masked}</code></div>
            {active.source === "environment" && (
              <div className="muted small">This key comes from the <code>{active.key_env}</code> setting on your computer.
                Saving a key below replaces it inside the advisor.</div>
            )}
            <div className="row-gap">
              <button className="btn" disabled={!!busy} onClick={runTest}>{busy === "test" ? "Testing…" : "Test connection"}</button>
              {active.source === "settings" &&
                <button className="btn danger" disabled={!!busy} onClick={remove}>{busy === "remove" ? "Removing…" : "Remove saved key"}</button>}
            </div>
            <TestResult t={test} />
          </div>
        )}

        <h4>{active ? "Change provider or key" : "Set up AI in three steps"}</h4>
        <ol className="ai-steps">
          <li>
            <div className="step-label">Choose a provider</div>
            <div className="providers" role="radiogroup" aria-label="AI provider">
              {info?.llm.providers.map((x) => (
                <label key={x.id} className={provider === x.id ? "provider on" : "provider"}>
                  <input type="radio" name="provider" value={x.id} checked={provider === x.id}
                    onChange={() => { setProvider(x.id); setFormError(null); setModel(""); }} />
                  <span className="provider-name">{x.label}{x.id === "openrouter" && <span className="badge rec">recommended</span>}</span>
                  <span className="provider-blurb">{x.blurb}</span>
                </label>
              ))}
            </div>
          </li>
          <li>
            <div className="step-label">Get an API key</div>
            {p && <p className="small">Sign in at {p.label}, create a key and copy it.{" "}
              <a href={p.key_url} target="_blank" rel="noreferrer">Open the {p.label} key page ↗</a></p>}
          </li>
          <li>
            <div className="step-label">Paste the key and save</div>
            <div className="key-row">
              <input className="key-input" type={showKey ? "text" : "password"} value={apiKey} autoComplete="off" spellCheck={false}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={sameProviderSaved ? "Saved key kept unless you paste a new one" : `Paste your key (usually starts with ${p?.key_hint ?? ""}…)`} />
              <button className="btn" type="button" onClick={() => setShowKey((v) => !v)}>{showKey ? "Hide" : "Show"}</button>
            </div>
            {keyLooksOff && <div className="warn small">{p?.label} keys usually start with <code>{p?.key_hint}</code>. Check you copied the right key.</div>}
            <details className="advanced">
              <summary>Advanced: choose a model</summary>
              <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={p?.default_model ?? ""} spellCheck={false} />
              <div className="muted small">Leave empty to use <code>{p?.default_model}</code>.
                {provider === "openrouter" && <> Any model id from <a href="https://openrouter.ai/models" target="_blank" rel="noreferrer">openrouter.ai/models</a> works.</>}</div>
            </details>
            <div className="row-gap">
              <button className="btn primary" disabled={!!busy || (!apiKey.trim() && !sameProviderSaved)} onClick={save}>
                {busy === "save" ? "Saving…" : busy === "test" ? "Testing…" : "Save and test connection"}
              </button>
            </div>
            {formError && <div className="error">{formError}</div>}
            {!active && <TestResult t={test} />}
          </li>
        </ol>
      </div>
    </section>
  );
}
