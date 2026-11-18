import { useEffect, useRef, useState } from "react";
import { askAdvisor } from "../api";
import type { AskAnswer, EnvInfo, IntegrationReport } from "../types";
import { CodeBlock, Inline } from "./common";

type TabId = "why" | "audit" | "pillars" | "kit" | "verify" | "setup";

/** Small, safe Markdown subset for AI answers: paragraphs, lists, **bold**, `code`, fenced code. No HTML. */
function Bold({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g);
  return <>{parts.map((p, i) => (p.startsWith("**") && p.endsWith("**") && p.length > 4
    ? <strong key={i}><Inline text={p.slice(2, -2)} /></strong> : <Inline key={i} text={p} />))}</>;
}

export function Markdown({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  const chunks = text.split(/(```[^\n]*\n[\s\S]*?```)/g);
  chunks.forEach((chunk, ci) => {
    if (chunk.startsWith("```")) {
      const lang = chunk.slice(3, chunk.indexOf("\n")).trim();
      blocks.push(<CodeBlock key={`c${ci}`} lang={lang || undefined}
        code={chunk.slice(chunk.indexOf("\n") + 1).replace(/```$/, "").trimEnd()} />);
      return;
    }
    let list: { ordered: boolean; items: string[] } | null = null;
    const flush = (k: string) => {
      if (!list) return;
      const items = list.items.map((it, i) => <li key={i}><Bold text={it} /></li>);
      blocks.push(list.ordered ? <ol key={k}>{items}</ol> : <ul key={k}>{items}</ul>);
      list = null;
    };
    chunk.split("\n").forEach((line, li) => {
      const k = `${ci}-${li}`;
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      const h = line.match(/^\s*#+\s+(.*)$/);
      if (ol || ul) {
        const ordered = !!ol;
        if (list && list.ordered !== ordered) flush(k + "f");
        if (!list) list = { ordered, items: [] };
        list.items.push((ol ?? ul)![1]);
      } else {
        flush(k + "f");
        if (h) blocks.push(<p key={k}><strong><Inline text={h[1]} /></strong></p>);
        else if (line.trim()) blocks.push(<p key={k}><Bold text={line} /></p>);
      }
    });
    flush(`${ci}-end`);
  });
  return <div className="md">{blocks}</div>;
}

const TAB_LABEL: Record<TabId, string> = {
  why: "Why QNX?", audit: "Audit", pillars: "3-pillar report", kit: "Porting kit", verify: "Verify on QNX", setup: "⚙ Setup",
};

interface Turn { role: "user" | "advisor"; text: string; follow_ups?: string[]; removed?: number }

function AskBox({ r, jobId, sample, env, suggestions, onOpenSetup }: {
  r: IntegrationReport; jobId: string | null; sample: string | null; env: EnvInfo | null; suggestions: string[];
  onOpenSetup: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { setTurns([]); setErr(null); }, [r.repo_url, r.generated_at_utc]);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [turns, busy]);
  const canAsk = !!env?.llm && (!!jobId || !!sample);

  const send = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setErr(null); setBusy(true); setQ("");
    const history = turns.map((t) => ({ role: t.role, text: t.text }));
    setTurns((t) => [...t, { role: "user", text }]);
    try {
      const a: AskAnswer = await askAdvisor({ jobId, sample }, text, history);
      setTurns((t) => [...t, { role: "advisor", text: a.answer, follow_ups: a.follow_ups, removed: a.removed }]);
    } catch (e) {
      setErr(String(e).replace(/^Error: \d+: /, ""));
      setTurns((t) => t.slice(0, -1)); setQ(text);
    }
    setBusy(false);
  };

  return (
    <section className="ask">
      <h3>Ask the advisor</h3>
      {!env?.llm ? (
        <p className="muted">Have a question, like “what is a resource manager?” or “how do I fix this?”. Turn on the
          AI assistant and ask it in plain English. It answers about <em>this</em> project and is fact-checked
          against your QNX SDP.{" "}
          <button className="btn" onClick={onOpenSetup}>Open Setup to add an AI key</button></p>
      ) : !canAsk ? (
        <p className="muted">Questions are available for analyzed repositories and the sample reports.</p>
      ) : (
        <>
          <p className="muted small">Ask anything about this project and QNX, in plain English. Answers come from
            {" "}{env.llm.split(":")[0]}, are based on this report, and are fact-checked: functions that don't exist in
            your QNX SDP and invented numbers are removed. Each question is a small paid AI request.</p>
          <div className="chat">
            {turns.map((t, i) => (
              <div key={i} className={`turn ${t.role}`}>
                <div className="who">{t.role === "user" ? "You" : "Advisor"}</div>
                {t.role === "user" ? <p>{t.text}</p> : <Markdown text={t.text} />}
                {t.role === "advisor" && !!t.removed && (
                  <div className="small muted">{t.removed} unverified claim(s) removed by the fact checker.</div>
                )}
                {t.role === "advisor" && i === turns.length - 1 && !!t.follow_ups?.length && (
                  <div className="chips">{t.follow_ups.map((f) => (
                    <button key={f} className="chip" disabled={busy} onClick={() => send(f)}>{f}</button>))}</div>
                )}
              </div>
            ))}
            {busy && <div className="turn advisor"><div className="who">Advisor</div><p className="muted">Thinking…</p></div>}
            <div ref={end} />
          </div>
          {turns.length === 0 && (
            <div className="chips">{suggestions.map((s) => (
              <button key={s} className="chip" disabled={busy} onClick={() => send(s)}>{s}</button>))}</div>
          )}
          <form className="ask-form" onSubmit={(e) => { e.preventDefault(); send(q); }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000}
              placeholder="Type a question, e.g. “What do I need to install first?”" aria-label="Your question" />
            <button className="btn primary" disabled={busy || !q.trim()}>{busy ? "Asking…" : "Ask"}</button>
          </form>
          {err && <div className="error">{err}</div>}
        </>
      )}
    </section>
  );
}

function progressKey(r: IntegrationReport) { return `qnx-advisor-path:${r.repo_url}`; }

export function StartTab({ r, jobId, sample, env, onOpenTab, onOpenSetup }: {
  r: IntegrationReport; jobId: string | null; sample: string | null; env: EnvInfo | null;
  onOpenTab: (t: Exclude<TabId, "setup">) => void; onOpenSetup: () => void;
}) {
  const g = r.beginner;
  const [done, setDone] = useState<number[]>([]);
  useEffect(() => {
    try { setDone(JSON.parse(localStorage.getItem(progressKey(r)) ?? "[]")); } catch { setDone([]); }
  }, [r.repo_url]);
  const toggle = (n: number) => {
    const next = done.includes(n) ? done.filter((x) => x !== n) : [...done, n];
    setDone(next);
    try { localStorage.setItem(progressKey(r), JSON.stringify(next)); } catch { /* storage unavailable */ }
  };
  if (!g) {
    return <p className="muted">This report was created before the “Start here” guide existed. Analyze the repository
      again to see it.</p>;
  }
  const open = (t?: TabId | null) => { if (!t) return; if (t === "setup") onOpenSetup(); else onOpenTab(t); };

  return (
    <div className="start">
      <section className="start-intro">
        <h3>New to QNX? Start here.</h3>
        <p><Inline text={g.intro.replace(/^New to QNX\? Start here\.\s*/, "")} /></p>
      </section>

      <h3>QNX in a few ideas</h3>
      <div className="concepts">
        {g.concepts.map((c) => (
          <article key={c.id} className="concept">
            <h4>{c.term}</h4>
            <p><Inline text={c.plain} /></p>
            {c.analogy && <p className="analogy">💡 {c.analogy}</p>}
            {c.why_here && <p className="why-here"><strong>In this project:</strong> <Inline text={c.why_here} /></p>}
          </article>
        ))}
      </div>

      <h3>Your path to QNX <span className="muted small">({done.length}/{g.path.length} done; ticks are saved in this browser)</span></h3>
      <ol className="path">
        {g.path.map((s) => (
          <li key={s.n} className={done.includes(s.n) ? "done" : ""}>
            <label className="path-head">
              <input type="checkbox" checked={done.includes(s.n)} onChange={() => toggle(s.n)} />
              <strong>{s.title}</strong>{s.optional && <span className="badge">optional</span>}
            </label>
            <p className="muted">{s.why}</p>
            {s.how.length > 0 && <ul>{s.how.map((h, i) => <li key={i}><Inline text={h} /></li>)}</ul>}
            <div className="path-foot">
              {s.done_when && <span className="small"><strong>Done when:</strong> {s.done_when}</span>}
              {s.tab && <button className="btn" onClick={() => open(s.tab)}>Open {TAB_LABEL[s.tab]}</button>}
            </div>
          </li>
        ))}
      </ol>

      <AskBox r={r} jobId={jobId} sample={sample} env={env} suggestions={g.suggested_questions} onOpenSetup={onOpenSetup} />
    </div>
  );
}
