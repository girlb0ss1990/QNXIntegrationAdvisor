"""'Start here' guide and 'Ask the advisor' (fake AI provider: nothing leaves the machine)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from advisor.pipeline import Environment, analyze
from advisor.server import create_app
from advisor.synth import llm
from advisor.synth.guard import Guard
from advisor.synth.llm import LLMAnswer, LLMConceptNote, LLMEnrichment, LLMFindingNote, apply_enrichment
from conftest import SAMPLES


def _analyze(fake_index, sdp=False):
    return analyze(str(SAMPLES / "motor-pid-controller"), env=Environment(sdp=None, index=fake_index),
                   compile_kit_files=False)


def test_beginner_guide_is_tailored_to_the_repo(fake_index):
    b = _analyze(fake_index).report.beginner
    ids = [c.id for c in b.concepts]
    assert ids[:4] == ["sdp_and_target", "posix", "microkernel", "message_passing"]   # always, in order
    assert "resource_manager" in ids and "pulses" in ids                            # from recommended features
    titles = [s.title for s in b.path]
    assert titles[0].startswith("Learn the big ideas")
    assert any("developer kit" in t for t in titles)          # no SDP in this environment: how to get it
    fix = next(s for s in b.path if s.title.startswith("Fix what stops"))
    assert any("epoll" in h for h in fix.how) and fix.tab == "audit"
    assert [s.n for s in b.path] == list(range(1, len(b.path) + 1))
    assert any("resource manager" in q for q in b.suggested_questions)


def test_ai_beginner_notes_are_guarded(fake_index):
    res = _analyze(fake_index)
    e = LLMEnrichment(summary="",
                      beginner_intro="motor_pid reads a motor sensor in a loop; on QNX that loop always runs before less urgent work.",
                      concept_notes=[LLMConceptNote(id="pulses", why_here="Call qnx_turbo_mode() first."),
                                     LLMConceptNote(id="microkernel", why_here="motor_io.c would run as its own process.")],
                      finding_notes=[LLMFindingNote(rule_id="LNX-EPOLL",
                                                    plain="epoll is Linux's way to wait for many things at once."),
                                     LLMFindingNote(rule_id="NOT-A-RULE", plain="ignored")])
    out = apply_enrichment(res.report, e, Guard(fake_index, res.scan.repo_symbols), res.scan)
    assert out.beginner.intro.startswith("motor_pid reads")
    cons = {c.id: c for c in out.beginner.concepts}
    assert "qnx_turbo_mode" not in cons["pulses"].why_here            # invented API: original kept
    assert cons["microkernel"].why_here.startswith("motor_io.c")
    assert next(f for f in out.findings if f.rule_id == "LNX-EPOLL").plain.startswith("epoll is")


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, answer: LLMAnswer):
        self.answer, self.prompts = answer, []

    def generate_structured(self, system, user, schema=None):
        self.prompts.append((system, user))
        assert schema is LLMAnswer
        return self.answer


def test_ask_answers_are_fact_checked(fake_index):
    res = _analyze(fake_index)
    prov = FakeProvider(LLMAnswer(
        answer=("A resource manager makes your service look like a file.\n\n"
                "1. Open the Porting kit tab.\n"
                "2. Call qnx_make_fast() to speed it up.\n"
                "3. It is 10x faster than Linux.\n\n"
                "```c\nint fd = open(\"/dev/motor_pid\", O_RDWR);\n```\n\n"
                "```c\nmagic_qnx_init();\n```"),
        follow_ups=["What is a pulse?", "How do I use fake_api_call()?"]))
    out = llm.ask(res.report, "What is a resource manager?", [{"role": "user", "text": "hi"}], prov,
                  fake_index, res.scan.repo_symbols, [])
    a = out["answer"]
    assert "look like a file" in a and "1. Open the Porting kit tab." in a     # lists and line breaks kept
    assert "qnx_make_fast" not in a and "10x" not in a                          # invented API and number removed
    assert 'open("/dev/motor_pid"' in a and "magic_qnx_init" not in a           # bad code block replaced
    assert "could not be verified" in a
    assert out["follow_ups"] == ["What is a pulse?"] and out["removed"] >= 4
    system, user = prov.prompts[0]
    assert "beginner" in system.lower() and "<question>" in user and "Developer: hi" in user


def test_ask_endpoint_needs_an_ai_key(monkeypatch):
    for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "OPENAI_API_KEY",
              "QNX_ADVISOR_LLM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("advisor.settings.apply_settings", lambda: None)
    c = TestClient(create_app())
    r = c.post("/api/samples/motor-pid-controller/ask", json={"question": "What should I do first?"})
    assert r.status_code == 409 and "Setup" in r.json()["detail"]
    assert c.post("/api/samples/../x/ask", json={"question": "x"}).status_code in (404, 405)
    assert c.post("/api/samples/motor-pid-controller/ask", json={"question": ""}).status_code == 422
