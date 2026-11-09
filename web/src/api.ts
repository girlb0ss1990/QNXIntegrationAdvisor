import type { EnvInfo, IntegrationReport, JobEvent } from "./types";

declare const __STATIC_VIEWER__: boolean;
export const STATIC_VIEWER: boolean = __STATIC_VIEWER__;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function getEnv(target?: string): Promise<EnvInfo> {
  if (STATIC_VIEWER) {
    return { mode: "M0", mode_reason: "static viewer: pre-generated sample reports only", llm: null,
             tree_sitter: false, sdp: null, index: null, target: null };
  }
  const q = target ? `?target=${encodeURIComponent(target)}` : "";
  return json(await fetch(`api/env${q}`));
}

export interface SampleRef { name: string; url: string }

export async function listSamples(): Promise<SampleRef[]> {
  if (STATIC_VIEWER) return json(await fetch("reports/index.json"));
  return json(await fetch("api/samples"));
}

export async function getSample(ref: SampleRef): Promise<IntegrationReport> {
  return json(await fetch(STATIC_VIEWER ? ref.url : `api/samples/${ref.name}`));
}

export async function createJob(body: { source: string; ref?: string; arch: string; use_llm: boolean }): Promise<string> {
  const r = await json<{ job_id: string }>(await fetch("api/jobs", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }));
  return r.job_id;
}

export async function getReport(jobId: string): Promise<IntegrationReport> {
  return json(await fetch(`api/jobs/${jobId}/report`));
}

export async function startVerify(jobId: string, target: string, arch: string): Promise<number> {
  const r = await json<{ since: number }>(await fetch(`api/jobs/${jobId}/verify`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target, arch }),
  }));
  return r.since;
}

const EVENTS = ["clone", "scan", "sysroot", "rules", "synth", "guard", "kit", "qcc", "deploy", "verify",
  "bench", "done", "error", "verify_done", "verify_error"];

/** Subscribes to job progress (SSE). Returns an unsubscribe function. */
export function subscribe(jobId: string, since: number, onEvent: (e: JobEvent) => void): () => void {
  const es = new EventSource(`api/jobs/${jobId}/events?since=${since}`);
  for (const name of EVENTS) {
    es.addEventListener(name, (m) => {
      const data = JSON.parse((m as MessageEvent).data);
      onEvent({ event: name, data });
      if (["done", "error", "verify_done", "verify_error"].includes(name)) es.close();
    });
  }
  es.onerror = () => es.close();
  return () => es.close();
}
