import { useEffect, useId, useRef, useState } from "react";
import type { EvidenceType, Severity, SourceLocation } from "../types";

/** Renders `backtick` spans as inline code; everything else as plain text (no HTML injection). */
export function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`\n]+`)/g);
  return <>{parts.map((p, i) => (p.startsWith("`") && p.endsWith("`") && p.length > 2
    ? <code key={i}>{p.slice(1, -1)}</code> : <span key={i}>{p}</span>))}</>;
}

export function SeverityBadge({ s }: { s: Severity }) {
  return <span className={`badge sev-${s}`}>{s}</span>;
}

const SYSROOT_LABEL: Record<string, string> = {
  available: "available in sysroot",
  missing: "missing in your sysroot",
  unknown_no_sdp: "unverified (no SDP)",
};

export function SysrootBadge({ status }: { status: string }) {
  return <span className={`badge sys-${status}`}>{SYSROOT_LABEL[status] ?? status}</span>;
}

export function EvidenceBadge({ e }: { e: EvidenceType }) {
  return <span className={`badge ev-${e}`}>{e}</span>;
}

export function Loc({ l }: { l: SourceLocation }) {
  return <code className="loc" title={l.snippet}>{l.file_path}:{l.line_start}</code>;
}

export function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="codeblock">
      <button className="copy" onClick={() => {
        navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); });
      }}>{copied ? "copied" : "copy"}</button>
      <pre data-lang={lang}><code>{code}</code></pre>
    </div>
  );
}

/** Side-by-side before/after view with simple line diff highlighting (LCS). */
export function DiffView({ before, after }: { before: string | null; after: string | null }) {
  const a = (before ?? "").split("\n");
  const b = (after ?? "").split("\n");
  const n = a.length, m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i].trim() === b[j].trim() ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const keepA = new Set<number>(), keepB = new Set<number>();
  for (let i = 0, j = 0; i < n && j < m;) {
    if (a[i].trim() === b[j].trim()) { keepA.add(i++); keepB.add(j++); }
    else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
    else j++;
  }
  return (
    <div className="diff">
      <div className="diff-col">
        <div className="diff-head">Before (Linux)</div>
        <pre>{before ? a.map((line, i) => <div key={i} className={keepA.has(i) ? "" : "del"}>{line || " "}</div>)
          : <div className="muted">(new code)</div>}</pre>
      </div>
      <div className="diff-col">
        <div className="diff-head">After (QNX 8.0)</div>
        <pre>{after ? b.map((line, i) => <div key={i} className={keepB.has(i) ? "" : "add"}>{line || " "}</div>)
          : <div className="muted">(no code change)</div>}</pre>
      </div>
    </div>
  );
}

let mermaidPromise: Promise<typeof import("mermaid")["default"]> | null = null;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((m) => {
      const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
      m.default.initialize({ startOnLoad: false, theme: dark ? "dark" : "neutral", securityLevel: "strict" });
      return m.default;
    });
  }
  return mermaidPromise;
}

export function Mermaid({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = "m" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    loadMermaid()
      .then((m) => m.render(id, code))
      .then(({ svg }) => { if (alive && ref.current) ref.current.innerHTML = svg; })
      .catch((e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, [code, id]);
  if (err) return <CodeBlock code={code} lang="mermaid" />;
  return <div className="mermaid" ref={ref} />;
}
