from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from advisor import settings
from advisor.server import create_app

KEYS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "OPENAI_API_KEY",
        "QNX_ADVISOR_LLM", "QNX_ADVISOR_OPENROUTER_MODEL")


@pytest.fixture
def clean(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    settings._ORIGINAL_ENV.clear()
    yield tmp_path
    settings._restore_env()


def test_save_apply_mask_and_clear(clean, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-user-own-environment-key")
    settings.save_llm("openrouter", "sk-or-v1-abcdefghijklmnop1234", "google/gemini-2.5-pro")
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-abcdefghijklmnop1234"
    st = settings.llm_status()["active"]
    assert st["provider"] == "openrouter" and st["model"] == "google/gemini-2.5-pro"
    assert st["source"] == "settings" and st["key_masked"].endswith("1234") and "abcdef" not in st["key_masked"]
    # model-only change keeps the saved key
    settings.save_llm("openrouter", None, None)
    assert settings.llm_status()["active"]["model"] == "anthropic/claude-opus-5.5"
    settings.clear_llm()
    assert "OPENROUTER_API_KEY" not in os.environ
    assert settings.llm_status()["active"]["provider"] == "gemini"   # user's own env var is back in charge


def test_save_rejects_bad_input(clean):
    with pytest.raises(settings.SettingsError):
        settings.save_llm("openrouter", "", None)
    with pytest.raises(settings.SettingsError):
        settings.save_llm("openrouter", "sk-or with spaces in it", None)
    with pytest.raises(settings.SettingsError):
        settings.save_llm("nope", "sk-or-v1-abcdefghijklmnop", None)


def test_setup_api_never_returns_full_key_and_blocks_cross_site(clean):
    c = TestClient(create_app())
    r = c.post("/api/settings/llm", json={"provider": "openai", "api_key": "sk-proj-secretsecretsecret9999"})
    assert r.status_code == 200
    body = c.get("/api/setup").text
    assert "secretsecret" not in body and "9999" in body
    assert {ch["id"] for ch in c.get("/api/setup").json()["checks"]} >= {"git", "parser", "ai", "sdp"}
    evil = c.post("/api/settings/llm", json={"provider": "openai", "api_key": "sk-attacker-key-000000"},
                  headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert c.delete("/api/settings/llm", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
