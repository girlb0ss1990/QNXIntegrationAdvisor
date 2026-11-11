"""Optional LLM synthesizer (mode M2). Provider-agnostic; every output goes through the guard.

Providers (pick with QNX_ADVISOR_LLM=openrouter|claude|gemini|openai, default: first with a key set,
in that order):
  openrouter - REST chat completions via OpenRouter, any model id (OPENROUTER_API_KEY,
               QNX_ADVISOR_OPENROUTER_MODEL, default anthropic/claude-opus-5.5)
  claude  - official `anthropic` SDK, structured output via messages.parse (ANTHROPIC_API_KEY or `ant auth login`)
  gemini  - REST generateContent with JSON output (GEMINI_API_KEY)
  openai  - REST chat completions with JSON output (OPENAI_API_KEY)

LLM output is never executed. If the provider fails, refuses, or returns invalid JSON after two
repair attempts, the deterministic report is used unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, Field, ValidationError

from ..models import Improvement, IntegrationReport, SourceLocation
from ..scanner import ScanResult
from ..sdp.indexer import INDEX_DIR, SysrootIndex
from .guard import Guard

PROMPTS = Path(__file__).with_name("prompts")
MAX_EXCERPTS, MAX_EXCERPT_LINES = 30, 40


# ---------------------------------------------------------------- output schema
class LLMFeatureNote(BaseModel):
    feature: str
    rationale: str
    diagram_mermaid: Optional[str] = None


class LLMStepNote(BaseModel):
    n: int
    explanation: str
    after_code: Optional[str] = None


class LLMImprovement(BaseModel):
    dimension: Literal["determinism_latency", "fault_isolation_recovery", "ipc_efficiency",
                       "security_least_privilege", "maintainability_portability"]
    current_limitation: str
    qnx_improvement: str
    file_path: str
    line: int


class LLMEnrichment(BaseModel):
    summary: str
    features: list[LLMFeatureNote] = Field(default_factory=list)
    steps: list[LLMStepNote] = Field(default_factory=list)
    extra_improvements: list[LLMImprovement] = Field(default_factory=list, max_length=5)


class Provider(Protocol):
    name: str
    model: str

    def generate_structured(self, system: str, user: str) -> LLMEnrichment: ...


class LLMError(RuntimeError):
    pass


# ---------------------------------------------------------------- providers
class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("QNX_ADVISOR_MODEL", "claude-opus-5-5")

    def generate_structured(self, system: str, user: str) -> LLMEnrichment:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("pip install anthropic to use the Claude provider") from e
        client = anthropic.Anthropic()
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=LLMEnrichment,
            )
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Claude API unreachable: {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude API rate limit") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}") from e
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined the request")
        if response.parsed_output is None:
            raise LLMError(f"no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output


class _JsonRestProvider:
    """Shared repair loop for providers that return a JSON string."""
    name = "rest"
    model = ""

    def _call(self, system: str, user: str) -> str:  # pragma: no cover - network
        raise NotImplementedError

    def generate_structured(self, system: str, user: str) -> LLMEnrichment:
        schema = json.dumps(LLMEnrichment.model_json_schema())
        prompt = f"{user}\n\nReturn only JSON matching this JSON Schema:\n{schema}"
        last_err = ""
        for _ in range(3):                      # first try + 2 repair retries
            text = self._call(system, prompt if not last_err else
                              f"{prompt}\n\nYour previous output was invalid: {last_err[:800]}. Return corrected JSON only.")
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            try:
                return LLMEnrichment.model_validate_json(text)
            except ValidationError as e:
                last_err = str(e)
        raise LLMError(f"{self.name}: invalid JSON after 2 repair attempts")


class GeminiProvider(_JsonRestProvider):
    name = "gemini"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("QNX_ADVISOR_GEMINI_MODEL", "gemini-2.5-pro")

    def _call(self, system: str, user: str) -> str:  # pragma: no cover - network
        import httpx
        key = os.environ["GEMINI_API_KEY"]
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": key},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}],
                  "generationConfig": {"responseMimeType": "application/json"}},
            timeout=180,
        )
        if r.status_code != 200:
            raise LLMError(f"Gemini API error {r.status_code}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


class _ChatCompletionsProvider(_JsonRestProvider):
    """OpenAI-compatible /chat/completions endpoint (OpenAI itself, OpenRouter)."""
    name = "chat"
    url = ""
    key_env = ""
    label = ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ[self.key_env]}"}

    def _call(self, system: str, user: str) -> str:  # pragma: no cover - network
        import httpx
        r = httpx.post(
            self.url, headers=self._headers(),
            json={"model": self.model, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=180,
        )
        if r.status_code != 200:
            raise LLMError(f"{self.label} API error {r.status_code}")
        body = r.json()
        if "error" in body:   # OpenRouter can return 200 with an upstream provider error
            raise LLMError(f"{self.label} error: {str(body['error'])[:200]}")
        return body["choices"][0]["message"]["content"]


class OpenAIProvider(_ChatCompletionsProvider):
    name = "openai"
    url = "https://api.openai.com/v1/chat/completions"
    key_env = "OPENAI_API_KEY"
    label = "OpenAI"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("QNX_ADVISOR_OPENAI_MODEL", "gpt-4.1")


class OpenRouterProvider(_ChatCompletionsProvider):
    """One key for many models. Model ids look like 'anthropic/claude-opus-5.5' or 'google/gemini-2.5-pro'."""
    name = "openrouter"
    url = "https://openrouter.ai/api/v1/chat/completions"
    key_env = "OPENROUTER_API_KEY"
    label = "OpenRouter"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("QNX_ADVISOR_OPENROUTER_MODEL", "anthropic/claude-opus-5.5")

    def _headers(self) -> dict[str, str]:
        # Optional attribution headers OpenRouter documents; they identify the app, not the user.
        return {**super()._headers(), "X-Title": "QNX Integration Advisor"}


def get_provider() -> Provider | None:
    choice = os.environ.get("QNX_ADVISOR_LLM", "").lower()
    # An OpenRouter key is the most explicit choice (it exists only to route models), so it goes first.
    if choice == "openrouter" or (not choice and os.environ.get("OPENROUTER_API_KEY")):
        return OpenRouterProvider()
    if choice == "claude" or (not choice and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))):
        return ClaudeProvider()
    if choice == "gemini" or (not choice and os.environ.get("GEMINI_API_KEY")):
        return GeminiProvider()
    if choice == "openai" or (not choice and os.environ.get("OPENAI_API_KEY")):
        return OpenAIProvider()
    return None


def llm_configured() -> str | None:
    p = get_provider()
    if p is None:
        return None
    import importlib.util
    lib = "anthropic" if isinstance(p, ClaudeProvider) else "httpx"
    if importlib.util.find_spec(lib) is None:
        return None   # key present but the client library is not installed: AI mode would only fall back
    return f"{p.name}:{p.model}"


# ---------------------------------------------------------------- context building
def _excerpts(sr: ScanResult, report: IntegrationReport) -> list[dict]:
    out, seen = [], set()
    for f in report.findings:
        for loc in f.locations[:3]:
            if len(out) >= MAX_EXCERPTS:
                return out
            key = (loc.file_path, loc.line_start // 20)
            if key in seen:
                continue
            seen.add(key)
            lines = sr.source_text(loc.file_path)
            if not lines:
                continue
            a = max(0, loc.line_start - 8)
            b = min(len(lines), a + MAX_EXCERPT_LINES)
            out.append({"file": loc.file_path, "first_line": a + 1, "code": "\n".join(lines[a:b])})
    return out


def build_user_prompt(sr: ScanResult, report: IntegrationReport, idx: SysrootIndex | None, allowed: set[str]) -> str:
    det = report.model_dump(include={"summary", "roles", "service_name", "findings", "pillar1_features",
                                     "pillar2_improvements", "pillar3_steps"})
    for f in det["findings"]:
        for loc in f["locations"]:
            loc.pop("snippet", None)
    cap = idx.summary() if idx else {"note": "no SDP installed; availability unverified"}
    return (
        "<deterministic_report>\n" + json.dumps(det, indent=1)[:60000] + "\n</deterministic_report>\n"
        "<sysroot_capabilities>\n" + json.dumps(cap) + "\n</sysroot_capabilities>\n"
        "<allowed_apis>\n" + " ".join(sorted(allowed)) + "\n</allowed_apis>\n"
        "<repo_excerpts>\n" + json.dumps(_excerpts(sr, report), indent=1) + "\n</repo_excerpts>\n"
        "Improve the report for this specific repository: a 3-5 sentence summary, a repo-specific rationale "
        "(and optionally a diagram) for each recommended feature, clearer explanations (and optionally better "
        "after_code) for the steps by number, and up to 5 extra improvements that cite a real file and line."
    )


def _cache_path(report: IntegrationReport, model: str, ruleset: str) -> Path:
    key = hashlib.sha256(f"{report.repo_url}|{report.commit_sha}|{ruleset}|{model}".encode()).hexdigest()[:24]
    return INDEX_DIR / "llm-cache" / f"{key}.json"


def enrich(report: IntegrationReport, sr: ScanResult, idx: SysrootIndex | None, provider: Provider,
           ruleset: str, use_cache: bool = True) -> tuple[IntegrationReport, str]:
    """Returns (report, status message). Never raises for provider problems."""
    guard = Guard(idx, sr.repo_symbols)
    allowed = set(guard.allowed)   # rule DB + repo symbols; the full sysroot list is too large for a prompt
    cache = _cache_path(report, provider.model, ruleset)
    enrichment: LLMEnrichment | None = None
    if use_cache and report.commit_sha != "local" and cache.exists():
        try:
            enrichment = LLMEnrichment.model_validate_json(cache.read_text(encoding="utf-8"))
        except ValidationError:
            enrichment = None
    if enrichment is None:
        system = (PROMPTS / "system.md").read_text(encoding="utf-8")
        try:
            enrichment = provider.generate_structured(system, build_user_prompt(sr, report, idx, allowed))
        except LLMError as e:
            return report, f"LLM skipped: {e}"
        except Exception as e:  # provider SDK/network surprises must not break the report
            return report, f"LLM skipped: {type(e).__name__}"
        if report.commit_sha != "local":
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(enrichment.model_dump_json(), encoding="utf-8")
    return apply_enrichment(report, enrichment, guard, sr), f"LLM enrichment applied ({provider.name}:{provider.model})"


_MERMAID_START = re.compile(r"^\s*(flowchart|graph)\s+(LR|TB|TD|RL|BT)\b")


def _diagram_ok(d: str | None) -> bool:
    return bool(d) and bool(_MERMAID_START.match(d)) and "\\n" not in d and len(d) < 3000


def apply_enrichment(report: IntegrationReport, e: LLMEnrichment, guard: Guard, sr: ScanResult) -> IntegrationReport:
    r = report.model_copy(deep=True)
    s = guard.filter_text(e.summary)
    if s:
        r.summary = r.summary + " " + s
    feats = {f.feature: f for f in r.pillar1_features}
    for note in e.features:
        f = feats.get(note.feature)
        if not f:
            continue
        txt = guard.filter_text(note.rationale)
        if txt:
            f.rationale = txt
        if note.diagram_mermaid:
            labels = " ".join(re.findall(r'"([^"]*)"', note.diagram_mermaid))
            if _diagram_ok(note.diagram_mermaid) and guard.filter_text(labels) == labels.strip():
                f.diagram_mermaid = note.diagram_mermaid.strip()
            else:
                guard._flag("diagram")
    steps = {s.n: s for s in r.pillar3_steps}
    for note in e.steps:
        st = steps.get(note.n)
        if not st:
            continue
        txt = guard.filter_text(note.explanation)
        if txt:
            st.explanation = txt
        if note.after_code:
            code = guard.filter_code(note.after_code)
            if code:
                st.after_code = code
                st.qcc_syntax_check = "skipped"
    for imp in e.extra_improvements:
        lines = sr.source_text(imp.file_path)
        if not lines or not (1 <= imp.line <= len(lines)):
            guard._flag(f"location:{imp.file_path}:{imp.line}")
            continue
        lim, q = guard.filter_text(imp.current_limitation), guard.filter_text(imp.qnx_improvement)
        if not lim or not q:
            continue
        r.pillar2_improvements.append(Improvement(
            dimension=imp.dimension, current_limitation=lim, qnx_improvement=q, evidence_type="static",
            evidence_locations=[SourceLocation(file_path=imp.file_path, line_start=imp.line, line_end=imp.line,
                                               snippet=lines[imp.line - 1].strip()[:300])],
        ))
    r.unverified_claims_removed += guard.result.removed
    r.mode = "M2" if r.mode == "M1" else r.mode
    return r
