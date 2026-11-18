"""'Start here': a plain-English guide for developers who have never used QNX.

Deterministic: the concepts come from rules/concepts.yaml (chosen by the features recommended for this
repository) and the learning path is built from the report itself (its blockers, kit files and steps).
The optional AI layer may rewrite the intro and the "why this matters here" lines; it cannot add concepts
or steps.
"""
from __future__ import annotations

from ..models import BeginnerGuide, Concept, IntegrationReport, LearningStep
from ..rules import load_concepts

FIT_PLAIN = {
    "strong": "QNX is a strong fit: this is the kind of time-critical, device or service code QNX is built for.",
    "good": "QNX is a good fit: the project would clearly gain from at least one of QNX's main strengths.",
    "possible": "QNX could help, mainly with reliability and security rather than timing.",
    "limited": "QNX would add limited benefit, but the code can still be ported if you need it on QNX.",
}
SEV_ORDER = {"blocker": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _concepts(report: IntegrationReport) -> list[Concept]:
    feats = {f.feature for f in report.pillar1_features}
    out = []
    for cid, c in sorted(load_concepts().items(), key=lambda kv: kv[1].get("order", 99)):
        if c.get("always") or feats & set(c.get("features", [])):
            out.append(Concept(id=cid, term=c["term"], plain=" ".join(c["plain"].split()),
                               analogy=c.get("analogy", ""),
                               why_here=" ".join(c.get("why_here", "").split()).format(service=report.service_name)))
    return out


def _loc(f) -> str:
    return f" ({f.locations[0].file_path}:{f.locations[0].line_start})" if f.locations else ""


def _path(report: IntegrationReport, sdp: bool) -> list[LearningStep]:
    svc = report.service_name
    steps: list[LearningStep] = []

    def add(**kw) -> None:
        steps.append(LearningStep(n=len(steps) + 1, **kw))

    add(title="Learn the big ideas (5 minutes)",
        why="A few QNX ideas explain almost everything in this report.",
        how=["Read the cards in “QNX in a few ideas” below.",
             "Then open the Why QNX? tab to see which of them matter for this project, with evidence."],
        done_when="You can say in one sentence why this project would (or would not) benefit from QNX.",
        tab="why")
    if not sdp:
        add(title="Get the free QNX developer kit (SDP 8.0)",
            why="The QNX compiler (qcc) and libraries come from the SDP. Without it the tool can analyze, but not "
                "build or run anything on QNX.",
            how=["Create a free myQNX account and request a QNX Everywhere non-commercial licence.",
                 "Install QNX Software Center and use it to install QNX SDP 8.0. On Windows, install it inside "
                 "WSL Ubuntu.",
                 "Restart this tool (on Windows: start.bat, then answer Y to QNX mode)."],
            done_when="Setup shows “QNX SDP 8.0: Ready”.", tab="setup")
    add(title="See QNX running on your PC",
        why="You don't need special hardware. A QNX 8.0 virtual machine runs inside your computer.",
        how=["Open ⚙ Setup.", "If “QNX 8.0 target” is not green, press Start QNX virtual machine and wait about "
             "a minute."],
        done_when="Setup shows “QNX 8.0 target: Ready”.", tab="setup", optional=not sdp)
    add(title=f"Run the generated {svc} code on QNX",
        why="This proves the generated starting point builds with qcc and runs on QNX before you change your own "
            "code.",
        how=["Open the Verify on QNX tab.", "Press Run on QNX 8.0 and watch the log."],
        done_when="Every line of the result checklist shows ✓.", tab="verify", optional=not sdp)

    worst = sorted(report.findings, key=lambda f: SEV_ORDER.get(f.severity, 9))
    blockers = [f for f in worst if f.severity in ("blocker", "high")][:5]
    if blockers:
        add(title="Fix what stops the code from building on QNX",
            why="Blockers use Linux-only features that don't exist on QNX, so they must be changed first. High "
                "items build, but behave differently.",
            how=[f"{f.title}{_loc(f)}: see the Audit tab for the QNX replacement." for f in blockers],
            done_when="The Audit tab has no blockers left when you analyze your updated code.", tab="audit")
    if report.applicable:                 # the kit always contains cmake/qnx8-toolchain.cmake
        add(title="Build your own project with the QNX compiler",
            why="Building often (and early) shows the remaining problems as compiler errors.",
            how=["Download the porting kit (Porting kit tab) and copy its cmake/ and include/ folders into your "
                 "project.",
                 "In WSL or Linux, load the QNX tools: `source ~/qnx800/qnxsdp-env.sh`",
                 "Then build: `cmake -B build-qnx -DCMAKE_TOOLCHAIN_FILE=cmake/qnx8-toolchain.cmake && cmake --build build-qnx`",
                 "`PORTING_GUIDE.md` in the kit explains each file."],
            done_when="The build finishes without errors.", tab="kit")
    if report.pillar3_steps:
        add(title=f"Work through the {len(report.pillar3_steps)} porting steps",
            why="Each step changes one thing, shows the code before and after, and gives a command to check it.",
            how=[f"Step {s.n}: {s.title} (effort {s.est_effort})" for s in report.pillar3_steps[:6]] +
                (["…and the rest in the 3-pillar report."] if len(report.pillar3_steps) > 6 else []),
            done_when="Every step's check command succeeds.", tab="pillars")
    add(title="Test on real hardware when timing matters",
        why="A virtual machine shares your PC with everything else, so its timings are only a rough guide.",
        how=["QNX 8.0 runs on a Raspberry Pi 5; build for aarch64le (the arch selector next to Analyze).",
             "Run the same verification against the board."],
        done_when="You have measurements from the hardware you will ship on.", tab="verify", optional=True)
    return steps


def build_beginner(report: IntegrationReport, sdp: bool) -> BeginnerGuide:
    svc = report.service_name
    fit = FIT_PLAIN.get(report.qnx_fit.level, "") if report.qnx_fit else ""
    n_block = sum(f.severity == "blocker" for f in report.findings)
    intro = (f"New to QNX? Start here. {fit} The tool found {len(report.findings)} place(s) in {svc} that use "
             f"Linux-only features" + (f", {n_block} of which must change before it builds on QNX" if n_block else "")
             + ". Below are the QNX ideas you need for this project, then a step-by-step path from where you are "
             "now to running on QNX.")
    questions = ["What is QNX, and why would I use it instead of Linux?",
                 "What should I do first?"]
    if report.findings:
        questions.append(f"Explain “{report.findings[0].title}” in plain English. How do I fix it?")
    if any(f.feature == "resource_manager" for f in report.pillar1_features):
        questions.append(f"What is a resource manager, and how would /dev/{svc} be used?")
    questions.append("How do I test this on the QNX virtual machine?")
    return BeginnerGuide(intro=intro, concepts=_concepts(report), path=_path(report, sdp),
                         suggested_questions=questions)
