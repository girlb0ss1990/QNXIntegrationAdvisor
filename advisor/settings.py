"""Local user settings (AI provider + key) and the beginner-facing setup checklist.

Keys are stored only on this machine, in ~/.qnx-advisor/settings.json (owner-only permissions where
the OS supports it), and are applied to this process as the same environment variables a power user
would set by hand. They are never returned to the browser in full, logged, or sent anywhere except
to the chosen provider's own API.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

SETTINGS_PATH = Path.home() / ".qnx-advisor" / "settings.json"


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    key_env: str
    model_env: str
    default_model: str
    key_url: str
    key_hint: str        # what a key usually starts with, to catch paste mistakes
    blurb: str


PROVIDERS: dict[str, ProviderInfo] = {
    "openrouter": ProviderInfo(
        "openrouter", "OpenRouter", "OPENROUTER_API_KEY", "QNX_ADVISOR_OPENROUTER_MODEL",
        "anthropic/claude-opus-5.5", "https://openrouter.ai/keys", "sk-or-",
        "One key and one bill for many models (Claude, Gemini, GPT and more). Easiest if you are new."),
    "claude": ProviderInfo(
        "claude", "Anthropic (Claude)", "ANTHROPIC_API_KEY", "QNX_ADVISOR_MODEL",
        "claude-opus-5-5", "https://console.anthropic.com/settings/keys", "sk-ant-",
        "Claude directly from Anthropic."),
    "gemini": ProviderInfo(
        "gemini", "Google Gemini", "GEMINI_API_KEY", "QNX_ADVISOR_GEMINI_MODEL",
        "gemini-2.5-pro", "https://aistudio.google.com/app/apikey", "AI",
        "Gemini directly from Google AI Studio."),
    "openai": ProviderInfo(
        "openai", "OpenAI", "OPENAI_API_KEY", "QNX_ADVISOR_OPENAI_MODEL",
        "gpt-4.1", "https://platform.openai.com/api-keys", "sk-",
        "GPT models directly from OpenAI."),
}

# Environment variables this module set, so "remove key" restores the user's own environment.
_ORIGINAL_ENV: dict[str, Optional[str]] = {}
_last_test: dict[str, dict] = {}


class SettingsError(ValueError):
    pass


# ---------------------------------------------------------------- storage
def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)          # owner read/write only (no-op beyond read-only flag on Windows)
    except OSError:
        pass
    tmp.replace(SETTINGS_PATH)


def _set_env(name: str, value: Optional[str]) -> None:
    if name not in _ORIGINAL_ENV:
        _ORIGINAL_ENV[name] = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _restore_env() -> None:
    for name, value in _ORIGINAL_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _ORIGINAL_ENV.clear()


def apply_settings() -> None:
    """Make saved settings take effect in this process (called at start-up and after every change)."""
    _restore_env()
    llm = load_settings().get("llm") or {}
    info = PROVIDERS.get(llm.get("provider", ""))
    if info and llm.get("api_key"):
        _set_env(info.key_env, llm["api_key"])
        _set_env("QNX_ADVISOR_LLM", info.id)
        _set_env(info.model_env, llm.get("model") or None)


def save_llm(provider: str, api_key: Optional[str], model: Optional[str]) -> None:
    info = PROVIDERS.get(provider)
    if info is None:
        raise SettingsError(f"unknown provider '{provider}'")
    data = load_settings()
    current = data.get("llm") or {}
    key = (api_key or "").strip()
    if not key and current.get("provider") == provider:
        key = current.get("api_key", "")       # keep the saved key when only the model changes
    if not key:
        raise SettingsError("Paste an API key first.")
    if any(c.isspace() for c in key) or len(key) < 12 or len(key) > 400:
        raise SettingsError("That does not look like an API key. Copy it again from the provider's website.")
    model = (model or "").strip() or None
    if model and (len(model) > 120 or any(c.isspace() for c in model)):
        raise SettingsError("The model name should be a single word such as " + info.default_model)
    data["llm"] = {"provider": provider, "api_key": key, "model": model, "saved_utc": _now()}
    _write_settings(data)
    _last_test.clear()
    apply_settings()


def clear_llm() -> None:
    data = load_settings()
    data.pop("llm", None)
    _write_settings(data)
    _last_test.clear()
    apply_settings()


def mask(key: str) -> str:
    return ("•" * 8 + key[-4:]) if len(key) > 8 else "•" * len(key)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------- AI status / connection test
def llm_status() -> dict:
    """What the UI shows about AI: which provider is active, where its key comes from, last test."""
    from .synth.llm import get_provider
    saved = load_settings().get("llm") or {}
    p = get_provider()
    out: dict = {"providers": [vars(i) for i in PROVIDERS.values()], "active": None}
    if p is None:
        return out
    info = PROVIDERS[p.name]
    key = os.environ.get(info.key_env, "")
    from_ui = saved.get("provider") == p.name and saved.get("api_key") == key
    out["active"] = {
        "provider": p.name, "label": info.label, "model": p.model, "default_model": info.default_model,
        "key_masked": mask(key) if key else "(signed in with ant auth)",
        "source": "settings" if from_ui else "environment",
        "key_env": info.key_env,
        "last_test": _last_test.get(f"{p.name}:{p.model}"),
    }
    return out


def _explain_http(status: int, provider: str) -> str:
    if status in (401, 403):
        return "The key was rejected. Check you copied the whole key, and that it is still active on the provider's website."
    if status == 402:
        return "The key works but the account has no credit. Add credit on the provider's website."
    if status == 404:
        return "The model name was not found. Clear the model box to use the default, or check the exact name."
    if status == 429:
        return "Too many requests or quota used up. Wait a minute, or check your plan's limits."
    if status >= 500:
        return f"{PROVIDERS[provider].label} is having problems right now ({status}). Try again shortly."
    return f"{PROVIDERS[provider].label} returned an error ({status})."


def test_llm() -> dict:
    """Make the smallest possible real request to the active provider and explain the outcome."""
    from .synth.llm import get_provider
    p = get_provider()
    if p is None:
        return {"ok": False, "message": "No AI provider is set up yet. Choose one and paste a key first."}
    started = time.monotonic()
    try:
        _ping(p.name, p.model)
        result = {"ok": True, "message": f"Connected to {PROVIDERS[p.name].label} using model {p.model}."}
    except _PingError as e:
        result = {"ok": False, "message": str(e)}
    result.update(latency_ms=round((time.monotonic() - started) * 1000), tested_utc=_now(),
                  provider=p.name, model=p.model)
    _last_test[f"{p.name}:{p.model}"] = result
    return result


class _PingError(Exception):
    pass


PING_PROMPT = "Reply with the single word OK."


def _ping(provider: str, model: str) -> None:  # pragma: no cover - network
    if provider == "claude":
        try:
            import anthropic
        except ImportError as e:
            raise _PingError("The Anthropic library is missing. Re-run start.bat / start.sh to install it.") from e
        try:
            anthropic.Anthropic().messages.create(
                model=model, max_tokens=16, messages=[{"role": "user", "content": PING_PROMPT}])
        except anthropic.APIConnectionError as e:
            raise _PingError("Could not reach Anthropic. Check your internet connection or proxy.") from e
        except anthropic.APIStatusError as e:
            raise _PingError(_explain_http(e.status_code, provider)) from e
        return

    try:
        import httpx
    except ImportError as e:
        raise _PingError("The httpx library is missing. Re-run start.bat / start.sh to install it.") from e
    info = PROVIDERS[provider]
    key = os.environ.get(info.key_env, "")
    try:
        if provider == "gemini":
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                           headers={"x-goog-api-key": key},
                           json={"contents": [{"role": "user", "parts": [{"text": PING_PROMPT}]}],
                                 "generationConfig": {"maxOutputTokens": 16}}, timeout=30)
        else:
            url = ("https://openrouter.ai/api/v1/chat/completions" if provider == "openrouter"
                   else "https://api.openai.com/v1/chat/completions")
            limit = {"max_tokens": 16} if provider == "openrouter" else {"max_completion_tokens": 16}
            r = httpx.post(url, headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "messages": [{"role": "user", "content": PING_PROMPT}], **limit},
                           timeout=30)
    except httpx.HTTPError as e:
        raise _PingError(f"Could not reach {info.label}. Check your internet connection or proxy.") from e
    if r.status_code != 200:
        raise _PingError(_explain_http(r.status_code, provider))
    try:
        body = r.json()
    except ValueError as e:
        raise _PingError(f"{info.label} sent an unexpected reply.") from e
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        code = err.get("code") if isinstance(err, dict) else None
        raise _PingError(_explain_http(code, provider) if isinstance(code, int)
                         else f"{info.label} reported an error: {str(err)[:200]}")


# ---------------------------------------------------------------- setup checklist
Status = Literal["ok", "warn", "missing", "optional"]


def _check(id: str, label: str, status: Status, detail: str, fix: str = "", required: bool = False,
           action: str = "") -> dict:
    return {"id": id, "label": label, "status": status, "detail": detail, "fix": fix, "required": required,
            "action": action}


# ---------------------------------------------------------------- QNX SDP installed inside WSL (Windows hosts)
_WSL_INDEX_RE = r"^/(home/[A-Za-z0-9._-]+|root)/\.qnx-advisor/sysroot-index-[A-Za-z0-9._-]+\.json$"
_WSL_SDP_RE = r"^/(home/[A-Za-z0-9._-]+|root)/qnx[0-9]+$"


def _wsl(script: str, timeout: int = 20) -> Optional[bytes]:
    """Run a fixed shell snippet in the default WSL distro. Output from Linux programs is UTF-8."""
    if platform.system() != "Windows" or not shutil.which("wsl.exe"):
        return None
    try:
        r = subprocess.run(["wsl.exe", "-e", "sh", "-c", script], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout


def find_wsl_sdp() -> Optional[dict]:
    """On Windows: is a QNX SDP (and an advisor library index built from it) installed inside WSL?"""
    import re
    out = _wsl("ls -d /home/*/qnx[0-9]* /root/qnx[0-9]* 2>/dev/null; "
               "ls -t /home/*/.qnx-advisor/sysroot-index-*.json /root/.qnx-advisor/sysroot-index-*.json 2>/dev/null")
    if not out:
        return None
    lines = [ln.strip() for ln in out.decode("utf-8", "replace").splitlines() if ln.strip()]
    sdps = [ln for ln in lines if re.match(_WSL_SDP_RE, ln)]
    idxs = [ln for ln in lines if re.match(_WSL_INDEX_RE, ln)]
    if not sdps and not idxs:
        return None
    return {"sdp": sdps[0] if sdps else None, "index": idxs[0] if idxs else None}


def import_wsl_index() -> dict:
    """Copy the library index (names of QNX headers/functions only, no QNX files) from WSL to this machine."""
    import re

    from .sdp.indexer import SysrootIndex, save_index
    found = find_wsl_sdp()
    if not found or not found.get("index"):
        sdp = found.get("sdp") if found else None
        if sdp:
            raise SettingsError(f"Found the QNX SDP in WSL ({sdp}) but it has not been indexed yet. In WSL run: "
                                f"source {sdp}/qnxsdp-env.sh && cd ~/qnx-integration-advisor && "
                                ".venv/bin/qnx-advisor index-sdp  then press the button again.")
        raise SettingsError("No QNX SDP was found inside WSL.")
    path = found["index"]
    assert re.match(_WSL_INDEX_RE, path)              # fixed shape: no shell metacharacters reach sh -c
    raw = _wsl(f"cat '{path}'", timeout=60)
    try:
        idx = SysrootIndex.from_json(json.loads((raw or b"").decode("utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        raise SettingsError("The index in WSL could not be read. Rebuild it there with qnx-advisor index-sdp.") from e
    saved = save_index(idx)
    return {"path": str(saved), **idx.summary()}


def setup_checks(sdp_path: Optional[str] = None) -> list[dict]:
    """Plain-language checklist for the Setup page. Never raises."""
    from .pipeline import Environment
    from .scanner import tree_sitter_available
    on_windows = platform.system() == "Windows"
    checks: list[dict] = []

    git = shutil.which("git")
    if git:
        try:
            ver = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ver = "git found"
        checks.append(_check("git", "Git (downloads repositories)", "ok", ver, required=True))
    else:
        checks.append(_check("git", "Git (downloads repositories)", "missing",
                             "Git is not installed, so GitHub/GitLab links cannot be analysed (local folders still work).",
                             "Install Git from https://git-scm.com/downloads, then restart the advisor.", required=True))

    if tree_sitter_available():
        checks.append(_check("parser", "C/C++ code parser", "ok", "tree-sitter is installed: accurate parsing.",
                             required=True))
    else:
        checks.append(_check("parser", "C/C++ code parser", "warn",
                             "Using the simpler fallback parser. Results still work but may miss some patterns.",
                             "Re-run start.bat / start.sh to reinstall the dependencies.", required=True))

    ai = llm_status()["active"]
    if ai is None:
        checks.append(_check("ai", "AI assistant (optional)", "optional",
                             "Not set up. Reports are complete without it; AI adds repo-specific wording and diagrams.",
                             "Choose a provider and paste an API key below."))
    else:
        t = ai.get("last_test")
        where = "saved in Setup" if ai["source"] == "settings" else f"from the {ai['key_env']} environment variable"
        if t and t["ok"]:
            checks.append(_check("ai", "AI assistant (optional)", "ok",
                                 f"{ai['label']} · {ai['model']} · key {where} · connection tested OK."))
        elif t:
            checks.append(_check("ai", "AI assistant (optional)", "missing",
                                 f"{ai['label']} · {ai['model']}: {t['message']}",
                                 "Fix the key or model below and press Test connection again."))
        else:
            checks.append(_check("ai", "AI assistant (optional)", "warn",
                                 f"{ai['label']} · {ai['model']} · key {where} · not tested yet.",
                                 "Press Test connection below to confirm it works."))

    env = Environment.detect(sdp_path)
    if not env.sdp and on_windows:
        return checks + _windows_sdp_checks(env)
    if env.sdp:
        from .sdp.toolchain import qcc_version
        checks.append(_check("sdp", "QNX SDP 8.0 (optional)", "ok",
                             f"SDP {env.sdp.version} found; compiler: {qcc_version(env.sdp) or 'qcc'}."))
        if env.index:
            s = env.index.summary()
            checks.append(_check("index", "QNX library index (optional)", "ok",
                                 f"{s['symbols']} QNX functions indexed: results are checked against your SDP."))
        else:
            checks.append(_check("index", "QNX library index (optional)", "warn",
                                 "The SDP is found but not indexed yet, so results are still unverified.",
                                 "Run: qnx-advisor index-sdp   (or: make index-sdp). It takes about a minute."))
    else:
        fix = ("The QNX SDP runs on Linux. Install it in WSL Ubuntu, then start the advisor there with: "
               "source ~/qnx800/qnxsdp-env.sh && ./start.sh" if on_windows else
               "Install QNX SDP 8.0 from myQNX, then run: source ~/qnx800/qnxsdp-env.sh && ./start.sh")
        checks.append(_check("sdp", "QNX SDP 8.0 (optional)", "optional",
                             "Not found. The advisor still works, but results are marked “unverified against "
                             "sysroot” and generated code is not compile-checked.", fix))
    return checks


def _windows_sdp_checks(env) -> list[dict]:
    wsl_start = "In WSL run: cd ~/qnx-integration-advisor && source ~/qnx800/qnxsdp-env.sh && ./start.sh"
    if env.index:
        s = env.index.summary()
        return [
            _check("index", "QNX library index", "ok",
                   f"{s['symbols']} functions from your QNX SDP {s['sdp_version']}: results are checked against "
                   "your SDP."),
            _check("sdp", "QNX compiler (optional)", "optional",
                   "The QNX compiler (qcc) only runs on Linux, so on Windows generated code is not compile-checked. "
                   "Everything else is verified.",
                   "For compile checks, start the advisor inside WSL. " + wsl_start),
        ]
    found = find_wsl_sdp()
    if found and found.get("index"):
        return [_check("sdp", "QNX SDP 8.0", "warn",
                       f"Your QNX SDP is installed inside WSL ({found['sdp'] or 'Linux'}), which this Windows app "
                       "cannot see directly. Its library index is ready to import.",
                       "Click the button to import it (names of QNX functions only; takes a few seconds).",
                       action="import_wsl_index")]
    if found and found.get("sdp"):
        return [_check("sdp", "QNX SDP 8.0", "warn",
                       f"Your QNX SDP is installed inside WSL ({found['sdp']}) but has not been indexed yet.",
                       f"In WSL run: source {found['sdp']}/qnxsdp-env.sh && cd ~/qnx-integration-advisor && "
                       ".venv/bin/qnx-advisor index-sdp   then press Check again here.")]
    return [_check("sdp", "QNX SDP 8.0 (optional)", "optional",
                   "Not found. The advisor still works, but results are marked \u201cunverified against sysroot\u201d "
                   "and generated code is not compile-checked.",
                   "The QNX SDP runs on Linux. Install it in WSL Ubuntu from myQNX, then " + wsl_start)]
