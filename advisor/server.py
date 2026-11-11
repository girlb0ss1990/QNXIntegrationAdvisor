"""Local FastAPI server: job orchestration, SSE progress, and the pre-built React SPA (spec 8.1).

One process, bound to 127.0.0.1 by default. QNX software never leaves this machine.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from .ingest.limits import MAX_CONCURRENT_JOBS
from .models import IntegrationReport

STATIC_DIR = Path(__file__).with_name("static")
SAMPLE_REPORTS = Path(__file__).resolve().parents[1] / "docs" / "sample-reports"
TERMINAL_EVENTS = {"done", "error", "verify_done", "verify_error"}


def detect_env(sdp_path: str | None = None, target: str | None = None) -> dict:
    from .pipeline import Environment
    from .scanner import tree_sitter_available
    from .synth.llm import llm_configured
    env = Environment.detect(sdp_path)
    info: dict = {
        "sdp": None, "index": None, "target": None, "llm": llm_configured(),
        "tree_sitter": tree_sitter_available(),
    }
    if env.sdp:
        from .sdp.toolchain import qcc_version
        info["sdp"] = {"path": str(env.sdp.root), "version": env.sdp.version, "archs": env.sdp.archs(),
                       "qcc_version": qcc_version(env.sdp)}
    if env.index:
        info["index"] = env.index.summary()
    reasons = []
    if env.sdp:
        reasons.append(f"SDP {env.sdp.version} found at {env.sdp.root}")
    else:
        reasons.append("no QNX SDP found (source qnxsdp-env.sh)")
    if env.sdp and not env.index:
        reasons.append("sysroot not indexed yet (run `qnx-advisor index-sdp`)")
    target_ok = False
    if target:
        from .verify.deploy import DeployError, Target, reachable
        try:
            target_ok, detail = reachable(Target(target))
        except DeployError as e:
            detail = str(e)
        info["target"] = {"spec": target, "reachable": target_ok, "detail": detail}
        reasons.append(f"target {target} {'reachable' if target_ok else 'unreachable'}")
    else:
        reasons.append("no target configured")
    reasons.append(f"LLM {'configured: ' + info['llm'] if info['llm'] else 'not configured'}")
    if env.sdp and target_ok:
        mode = "M3"
    elif info["llm"]:
        mode = "M2"
    else:
        mode = "M1"
    info["mode"] = mode
    info["mode_reason"] = "; ".join(reasons)
    return info


@dataclass
class Job:
    id: str
    source: str
    events: list[dict] = field(default_factory=list)
    status: str = "queued"
    report: Optional[IntegrationReport] = None
    cond: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, event: str, data: dict) -> None:
        with self.cond:
            self.events.append({"event": event, "data": data, "t": time.time()})
            self.cond.notify_all()


class JobRequest(BaseModel):
    source: str
    ref: Optional[str] = None
    arch: Literal["x86_64", "aarch64le"] = "x86_64"
    use_llm: bool = False


class LLMSettingsRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None


LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _is_local_origin(origin: str) -> bool:
    from urllib.parse import urlsplit
    try:
        return (urlsplit(origin).hostname or "") in {h.strip("[]") for h in LOCAL_ORIGIN_HOSTS}
    except ValueError:
        return False


class VerifyRequest(BaseModel):
    target: Optional[str] = None
    arch: Literal["x86_64", "aarch64le"] = "x86_64"


def create_app(sdp: str | None = None, target: str | None = None) -> FastAPI:
    from .settings import apply_settings
    apply_settings()          # saved AI key/model from the Setup page take effect for this process
    app = FastAPI(title="QNX Integration Advisor", version="0.1.0")
    jobs: dict[str, Job] = {}

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        # Any web page can send requests to localhost. Refuse state-changing requests that a browser
        # marks as coming from another site, so a malicious page cannot set keys or start jobs.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and not _is_local_origin(origin):
                return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        return await call_next(request)
    slots = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)
    state = {"target": target}

    def get_job(job_id: str) -> Job:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return job

    def require_report(job_id: str) -> IntegrationReport:
        job = get_job(job_id)
        if job.report is None:
            raise HTTPException(409, f"job is {job.status}")
        return job.report

    def run_job(job: Job, req: JobRequest) -> None:
        from .pipeline import Environment, analyze
        with slots:
            job.status = "running"
            try:
                res = analyze(req.source, ref=req.ref, arch=req.arch, use_llm=req.use_llm,
                              env=Environment.detect(sdp), emit=job.emit)
                job.report = res.report
                job.status = "done"
                job.emit("done", {"message": "report ready", "score": res.report.readiness_score})
            except Exception as e:     # surface every failure to the UI, never crash the server
                job.status = "error"
                job.emit("error", {"message": f"{type(e).__name__}: {e}"})

    @app.get("/api/env")
    def api_env(target: Optional[str] = None):
        return detect_env(sdp, target or state["target"])

    @app.post("/api/jobs")
    def api_create_job(req: JobRequest):
        from .ingest import IngestError, parse_url
        if req.source.startswith("https://"):
            try:
                parse_url(req.source)
            except IngestError as e:
                raise HTTPException(400, str(e)) from e
        elif not Path(req.source).expanduser().is_dir():
            raise HTTPException(400, "source must be a GitHub/GitLab/Bitbucket https URL or an existing local directory")
        job = Job(id=uuid.uuid4().hex[:12], source=req.source)
        jobs[job.id] = job
        threading.Thread(target=run_job, args=(job, req), daemon=True).start()
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str):
        job = get_job(job_id)
        return {"id": job.id, "status": job.status, "source": job.source, "events": len(job.events)}

    @app.get("/api/jobs/{job_id}/events")
    def api_events(job_id: str, since: int = 0):
        job = get_job(job_id)

        def stream():
            i = max(0, since)
            idle = 0.0
            while True:
                with job.cond:
                    if i >= len(job.events):
                        job.cond.wait(timeout=15)
                    batch = job.events[i:]
                if not batch:
                    idle += 15
                    yield ": keep-alive\n\n"
                    if idle > 1800:
                        return
                    continue
                for ev in batch:
                    i += 1
                    yield f"id: {i}\nevent: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
                    if ev["event"] in TERMINAL_EVENTS and job.status not in ("running", "verifying"):
                        return

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/jobs/{job_id}/report")
    def api_report(job_id: str):
        return JSONResponse(json.loads(require_report(job_id).model_dump_json()))

    @app.get("/api/jobs/{job_id}/report.md")
    def api_report_md(job_id: str):
        from .export import to_markdown
        return PlainTextResponse(to_markdown(require_report(job_id)), media_type="text/markdown")

    @app.get("/api/jobs/{job_id}/report.sarif")
    def api_report_sarif(job_id: str):
        from .export import to_sarif
        return JSONResponse(to_sarif(require_report(job_id)))

    @app.get("/api/jobs/{job_id}/kit.zip")
    def api_kit(job_id: str):
        from .kit.generator import kit_zip
        r = require_report(job_id)
        if not r.applicable:
            raise HTTPException(409, "no porting kit: repository has no C/C++ sources")
        name = f"qnx-kit-{r.service_name}"
        return Response(kit_zip(r.kit, name), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})

    @app.post("/api/jobs/{job_id}/verify")
    def api_verify(job_id: str, req: VerifyRequest):
        from .pipeline import Environment
        from .verify.deploy import DeployError, Target
        from .verify.target import run_verification
        job = get_job(job_id)
        report = require_report(job_id)
        if not report.applicable:
            raise HTTPException(409, "nothing to verify: repository has no C/C++ sources")
        env = Environment.detect(sdp)
        if env.sdp is None:
            raise HTTPException(409, "live verification needs a local QNX SDP 8.0")
        spec = req.target or state["target"]
        if not spec:
            raise HTTPException(400, "no target configured (user@host)")
        try:
            tgt = Target(spec)
        except DeployError as e:
            raise HTTPException(400, str(e)) from e
        state["target"] = spec

        def run():
            job.status = "verifying"
            try:
                rec = run_verification(report, env.sdp, tgt, req.arch, job.emit)
                job.status = "done"
                job.emit("verify_done", {"message": "verification record attached", "record": json.loads(rec.model_dump_json())})
            except Exception as e:
                job.status = "done"
                job.emit("verify_error", {"message": f"{type(e).__name__}: {e}"})

        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "since": len(job.events)}

    @app.get("/api/jobs/{job_id}/trace.kev")
    def api_trace(job_id: str):
        require_report(job_id)
        raise HTTPException(404, "no kernel trace captured for this job (tracelogger capture is optional)")

    # ----- Setup page: plain-language checklist, AI key management, connection test
    @app.get("/api/setup")
    def api_setup():
        from .settings import llm_status, setup_checks
        return {"checks": setup_checks(sdp), "llm": llm_status()}

    @app.post("/api/settings/llm")
    def api_save_llm(req: LLMSettingsRequest):
        from .settings import SettingsError, llm_status, save_llm
        try:
            save_llm(req.provider, req.api_key, req.model)
        except SettingsError as e:
            raise HTTPException(400, str(e)) from e
        return llm_status()

    @app.delete("/api/settings/llm")
    def api_clear_llm():
        from .settings import clear_llm, llm_status
        clear_llm()
        return llm_status()

    @app.post("/api/setup/import-wsl-index")
    def api_import_wsl_index():
        from .settings import SettingsError, import_wsl_index
        try:
            return import_wsl_index()
        except SettingsError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/settings/llm/test")
    def api_test_llm():
        from .settings import test_llm
        return test_llm()

    @app.get("/api/samples")
    def api_samples():
        if not SAMPLE_REPORTS.is_dir():
            return []
        return [{"name": p.stem, "url": f"/api/samples/{p.stem}"} for p in sorted(SAMPLE_REPORTS.glob("*.json"))]

    @app.get("/api/samples/{name}")
    def api_sample(name: str):
        p = SAMPLE_REPORTS / f"{name}.json"
        if not name.replace("-", "").replace("_", "").isalnum() or not p.exists():
            raise HTTPException(404, "unknown sample")
        return JSONResponse(json.loads(p.read_text(encoding="utf-8")))

    # ----- SPA
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if STATIC_DIR.is_dir():
            f = (STATIC_DIR / path).resolve()
            if path and f.is_file() and STATIC_DIR.resolve() in f.parents and f.name != "index.html":
                return FileResponse(f)   # hashed asset names: safe to cache
            # index.html must never be cached, or an updated install keeps loading the old UI bundle
            return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>QNX Integration Advisor</h1><p>The web UI is not built. Run <code>make web</code>, "
                            "or use the API at <a href='/docs'>/docs</a>.</p>")

    return app
