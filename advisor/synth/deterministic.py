"""Deterministic synthesizer (always on): builds all three pillars from rule hits,
role heuristics and templates. Complete and readable without any LLM (spec G4)."""
from __future__ import annotations

from collections import Counter

from ..models import FeatureRecommendation, Finding, Improvement, SourceLocation, Step
from ..rules import load_features, load_rules
from ..scanner import ScanResult
from ..sdp.indexer import SysrootIndex

SEV_REL = {"blocker": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
CATEGORY_ORDER = ["toolchain_build", "api_migration", "resmgr_conversion", "scheduling_timing",
                  "reliability_security", "deploy_verify"]
TOOLCHAIN_RULES = ["BLD-COMPILER", "LNX-LIBS", "LNX-SOCKLIB", "LNX-INOTIFY"]


def _rules_by_id():
    return {r.id: r for r in load_rules()}


def _main_file(sr: ScanResult) -> str:
    for h in sr.hits:
        if h.kind == "funcdef" and h.name == "main":
            return h.file
    return sr.files.rel(sr.files.sources[0]) if sr.files.sources else "(repository)"




_SRC_EXT = (".c", ".h", ".cc", ".cpp", ".hpp", ".cxx", ".hh")


def _before_snippet(sr: ScanResult, locs: list[SourceLocation]) -> str | None:
    """Real code from the repo: up to two call sites (not #include lines) with a little context."""
    code_locs = [l for l in locs if l.file_path.endswith(_SRC_EXT) and not l.snippet.lstrip().startswith("#include")]
    if not code_locs:
        other = next((l for l in locs if not l.file_path.endswith(_SRC_EXT)), None)
        return other.snippet if other else None
    first_file = code_locs[0].file_path
    chosen = [l for l in code_locs if l.file_path == first_file][:2]
    lines = sr.source_text(first_file)
    if not lines:
        return "\n".join(l.snippet for l in chosen)
    ranges: list[list[int]] = []
    for l in chosen:
        a, b = max(0, l.line_start - 2), min(len(lines), l.line_end + 2)
        if ranges and a <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], b)
        else:
            ranges.append([a, b])
    blocks = []
    for a, b in ranges:
        block = lines[a:b]
        indent = min((len(x) - len(x.lstrip()) for x in block if x.strip()), default=0)
        blocks.append("\n".join(x[indent:] for x in block).strip("\n"))
    return f"/* {first_file} */\n" + "\n/* ... */\n".join(blocks)


# ------------------------------------------------------------------------- Pillar 1
def build_pillar1(findings: list[Finding], sr: ScanResult, idx: SysrootIndex | None) -> list[FeatureRecommendation]:
    rules = _rules_by_id()
    catalogue = load_features()
    score: dict[str, int] = {}
    files: dict[str, Counter] = {}

    def bump(feature: str, rel: int, locs: list[SourceLocation] | None = None):
        score[feature] = max(score.get(feature, 0), rel)
        c = files.setdefault(feature, Counter())
        for loc in locs or []:
            c[loc.file_path] += 1

    for f in findings:
        if f.already_guarded:
            continue
        for tag in rules[f.rule_id].feature_tags:
            bump(tag, SEV_REL[f.severity], f.locations)
    roles = set(sr.roles)
    if "device_service" in roles:
        bump("resource_manager", 5)
    if "periodic_control_loop" in roles:
        bump("channels_pulses", 4)
        bump("tracelogger", 2)
    if "daemon" in roles:
        bump("ham", 3)
    if "ipc_server" in roles:
        bump("resource_manager", 3)
    if any(f.rule_id == "LNX-CPU-BUDGET" for f in findings):
        bump("hypervisor", 1)

    main_file = _main_file(sr)
    out: list[FeatureRecommendation] = []
    for feature, rel in sorted(score.items(), key=lambda kv: (-kv[1], kv[0])):
        spec = catalogue[feature]
        comp_counter = files.get(feature) or Counter()
        component = comp_counter.most_common(1)[0][0] if comp_counter else main_file
        fmt = {"component": f"`{component}`", "service": sr.service_name}
        apis = list(spec.get("apis", []))
        verified = bool(idx) and all(idx.known(a) for a in apis) and all(idx.has_header(h) for h in spec.get("headers", []))
        if idx:
            apis = [a for a in apis if idx.known(a)]
        diagram = spec.get("diagram")
        out.append(FeatureRecommendation(
            feature=feature, apis=apis, headers=spec.get("headers", []), target_component=component,
            rationale=" ".join(spec["rationale"].format(**fmt).split()), relevance=max(1, min(5, rel)),
            diagram_mermaid=diagram.replace("{service}", sr.service_name).strip() if diagram else None,
            verified_in_sysroot=verified,
        ))
    return out


# ------------------------------------------------------------------------- Pillar 2
def build_pillar2(findings: list[Finding], sr: ScanResult) -> list[Improvement]:
    rules = _rules_by_id()
    out: list[Improvement] = []
    for f in findings:
        imp = rules[f.rule_id].raw.get("improvement")
        if not imp or f.already_guarded:
            continue
        out.append(Improvement(
            dimension=imp["dimension"],
            current_limitation=" ".join(imp["limitation"].split()),
            evidence_locations=f.locations[:5],
            qnx_improvement=" ".join(imp["qnx"].split()),
            evidence_type="static",
        ))
    roles = set(sr.roles)
    if "periodic_control_loop" in roles:
        out.append(Improvement(
            dimension="determinism_latency",
            current_limitation="The periodic loop's wake-up lateness under background CPU load is unknown on QNX.",
            qnx_improvement=("Run the agent's timer benchmark (1 kHz pulse timer, SCHED_FIFO) with and without "
                             "low-priority load threads to measure wake-up lateness on your target."),
            evidence_type="qualitative", measurement_ref="timer_late_p99_us_loaded",
        ))
    if "device_service" in roles or "ipc_server" in roles:
        out.append(Improvement(
            dimension="fault_isolation_recovery",
            current_limitation="Device access and client handling live in one process with the application logic.",
            qnx_improvement=("As a resource manager the service is a separate process that clients reach through "
                             "open/read/devctl; it can be restarted without restarting its clients' code. "
                             "The agent measures the time from spawn until /dev/<service> appears."),
            evidence_type="qualitative", measurement_ref="resmgr_ready_ms",
        ))
        out.append(Improvement(
            dimension="ipc_efficiency",
            current_limitation="Clients exchange data with the service through Linux-specific mechanisms.",
            qnx_improvement=("QNX synchronous message passing copies data directly between address spaces and "
                             "inherits the client's priority. The agent's IPC benchmark measures MsgSend round trips."),
            evidence_type="qualitative", measurement_ref="ipc_rtt_p50_ns",
        ))
    return out


# ------------------------------------------------------------------------- Pillar 3
def build_pillar3(findings: list[Finding], sr: ScanResult, resmgr_excerpt: str, kit_toolchain_hint: str) -> list[Step]:
    rules = _rules_by_id()
    active = [f for f in findings if not f.already_guarded]
    by_id = {f.rule_id: f for f in active}
    steps: list[tuple[str, Step]] = []

    tc = [by_id[r] for r in TOOLCHAIN_RULES if r in by_id]
    if tc or sr.files.build_files:
        bullets = []
        for f in tc:
            s = rules[f.rule_id].raw.get("step", {})
            bullets.append(f"{f.title}: {s.get('explanation', f.guidance)}")
        expl = ("Cross-compile with the kit's toolchain file (qcc/q++ with -V gcc_nto<arch>)."
                + (" Changes needed: " + " ".join(bullets) if bullets else ""))
        src_ext = (".c", ".h", ".cc", ".cpp", ".hpp", ".cxx")
        before = "\n".join(dict.fromkeys(loc.snippet for f in tc for loc in f.locations[:3]
                                         if loc.snippet and not loc.file_path.endswith(src_ext))) or None
        steps.append(("toolchain_build", Step(
            n=0, title="Cross-compile with the QNX 8.0 toolchain", category="toolchain_build",
            affected_files=sorted({loc.file_path for f in tc for loc in f.locations})
            or [sr.files.rel(b) for b, _ in sr.files.build_files][:3],
            explanation=expl.strip(), before_code=before, after_code=kit_toolchain_hint,
            verify_command="cmake -B build-qnx -DCMAKE_TOOLCHAIN_FILE=cmake/qnx8-toolchain.cmake -DQNX_ARCH=x86_64 && cmake --build build-qnx",
            est_effort="S",
        )))

    for f in active:
        if f.rule_id in TOOLCHAIN_RULES:
            continue
        s = rules[f.rule_id].raw.get("step")
        if not s:
            continue
        before = _before_snippet(sr, f.locations) or s.get("before")
        steps.append((s["category"], Step(
            n=0, title=s["title"], category=s["category"],
            affected_files=sorted({l.file_path for l in f.locations}),
            explanation=" ".join(s.get("explanation", f.guidance).split()),
            before_code=(before or s.get("before") or None),
            after_code=(s.get("after") or "").rstrip() or None,
            verify_command=s.get("verify", ""), est_effort=s.get("effort", "M"),
        )))

    if "device_service" in sr.roles or "ipc_server" in sr.roles:
        steps.append(("resmgr_conversion", Step(
            n=0, title=f"Expose the service as a /dev/{sr.service_name} resource manager",
            category="resmgr_conversion",
            affected_files=[f"src/qnx_{sr.service_name}_resmgr.c", f"src/{sr.service_name}_dcmd.h"],
            explanation=("Start from the kit's resource-manager skeleton. Clients open /dev/"
                         f"{sr.service_name} and use read(), write() and devctl() instead of a private "
                         "socket or shared memory. The periodic work moves into the timer pulse handler, "
                         "which runs serialized with client requests in one thread."),
            before_code=None, after_code=resmgr_excerpt or None,
            verify_command=f"ls -l /dev/{sr.service_name} && {sr.service_name}ctl  # on the target",
            est_effort="L",
        )))

    steps.append(("deploy_verify", Step(
        n=0, title="Build, deploy and verify on a QNX 8.0 target", category="deploy_verify",
        affected_files=["Makefile.qnx", "target/run-qemu.sh"],
        explanation=("Build the kit binaries with qcc, boot the QEMU target with mkqnximage, copy the binaries over "
                     "SSH and run them under the advisor agent, which checks that the resource manager comes up "
                     "and measures timer and IPC behaviour."),
        before_code=None,
        after_code=None,
        verify_command=f"advisorctl verify /data/home/qnxuser/{sr.service_name}_resmgr --expect /dev/{sr.service_name} --timeout 5000",
        est_effort="M",
    )))

    steps.sort(key=lambda cs: CATEGORY_ORDER.index(cs[0]))
    result = []
    for i, (_, s) in enumerate(steps, 1):
        s.n = i
        result.append(s)
    return result


def build_summary(findings: list[Finding], score: int, sr: ScanResult, idx: SysrootIndex | None) -> str:
    c = Counter(f.severity for f in findings if not f.already_guarded)
    missing = [f.rule_id for f in findings if f.sysroot_status == "missing"]
    where = f"your QNX SDP {idx.sdp_version} sysroot" if idx else "QNX 8.0 (no SDP found, unverified)"
    parts = [
        f"{len(findings)} finding(s) across {len({l.file_path for f in findings for l in f.locations})} file(s): "
        f"{c.get('blocker', 0)} blocker, {c.get('high', 0)} high, {c.get('medium', 0)} medium, "
        f"{c.get('low', 0)} low, {c.get('info', 0)} info.",
    ]
    if idx:
        parts.append(f"{len(missing)} rule(s) depend on APIs missing from {where}.")
    else:
        parts.append(f"Availability was judged against {where}.")
    if sr.roles:
        parts.append("Detected roles: " + ", ".join(r.replace("_", " ") for r in sr.roles) + ".")
    if "device_service" in sr.roles:
        parts.append(f"Recommended shape on QNX: a /dev/{sr.service_name} resource manager driven by a pulse timer.")
    parts.append(f"Readiness score {score}/100 (deterministic formula).")
    return " ".join(parts)


# ---------------------------------------------------------------- "Why QNX?"
ROLE_PHRASE = {
    "periodic_control_loop": "a periodic control loop",
    "device_service": "opens Linux device files under /dev",
    "daemon": "runs as a background daemon",
    "ipc_server": "serves other processes (Unix sockets, message queues or shared memory)",
}
_RANK = {"high": 3, "medium": 2, "low": 1}
# What QNX is distinctively built for; a "good"/"strong" fit needs at least one of these with strong evidence.
CORE_BENEFITS = {"realtime_determinism", "fault_isolation", "message_passing", "safety_certification"}


def _lower_first(t: str) -> str:
    # "Sleep-based loop" -> "sleep-based loop"; keep names and acronyms ("Linux", "BSD", "SocketCAN") as they are
    first = t.split(" ", 1)[0]
    if len(first) > 1 and first[1:].islower() and first not in ("Linux", "POSIX"):
        return t[:1].lower() + t[1:]
    return t


def _loc(f: Finding) -> str:
    if not f.locations:
        return ""
    loc = f.locations[0]
    return f" in {loc.file_path}:{loc.line_start}"


def build_benefits(findings: list[Finding], sr: ScanResult, score: int, sysroot_verified: bool):
    """Benefits of running this repository on QNX, each backed by evidence from the scan."""
    from ..models import Benefit, QnxFit
    from ..rules import load_benefits
    svc = sr.service_name
    roles = set(sr.roles)
    active = [f for f in findings if not f.already_guarded]
    by_rule = {f.rule_id: f for f in active}
    out: list[Benefit] = []
    for bid, b in load_benefits().items():
        trig = b.get("triggers", {})
        hit_roles = [r for r in trig.get("roles", []) if r in roles]
        hit_rules = [by_rule[r] for r in trig.get("rules", []) if r in by_rule]
        any_finding = trig.get("any_finding") and active
        if not (hit_roles or hit_rules or any_finding):
            continue
        strength = b.get("base_strength", "medium")
        if not hit_roles and hit_rules and "rules_only_strength" in b:
            strength = b["rules_only_strength"]
        if set(hit_roles) & set(b.get("strong_roles", [])) or {f.rule_id for f in hit_rules} & set(b.get("strong_rules", [])):
            strength = "high"
        bits = [ROLE_PHRASE[r] for r in hit_roles] + [f"{_lower_first(f.title)}{_loc(f)}" for f in hit_rules]
        if any_finding and not bits:
            files = {loc.file_path for f in active for loc in f.locations}
            evidence = (f"The audit found {len(active)} Linux-specific pattern(s) across {len(files)} file(s); "
                        f"the readiness score is {score}/100.")
        else:
            evidence = "; ".join(bits[:3]) + (f"; and {len(bits) - 3} more" if len(bits) > 3 else "")
        why = " ".join(b["why"].split()).replace("{service}", svc).replace("{evidence}", evidence)
        locs = [f.locations[0] for f in hit_rules if f.locations][:4]
        out.append(Benefit(id=bid, title=b["title"], capability=b["capability"], why=why,
                           evidence_summary=evidence, evidence_locations=locs, strength=strength,
                           related_features=b.get("features", [])))
    out.sort(key=lambda x: -_RANK[x.strength])

    highs = [b for b in out if b.strength == "high"]
    mediums = [b for b in out if b.strength == "medium"]
    core_highs = [b for b in highs if b.id in CORE_BENEFITS]
    if len(core_highs) >= 2:
        level, headline = "strong", (f"Strong fit: {svc} does the kind of real-time, device or service work "
                                     "QNX is built for.")
    elif core_highs or len(highs) >= 2:
        top = (core_highs or highs)[0]
        level, headline = "good", f"Good fit: {svc} would mainly gain {top.title[0].lower() + top.title[1:]}."
    elif highs or len(mediums) >= 2:
        top = (highs or mediums)[0]
        level, headline = "possible", (f"Possible fit: QNX would mainly add reliability and security benefits, "
                                       f"such as {top.title[0].lower() + top.title[1:]}.")
    else:
        level, headline = "limited", ("Limited benefit: little real-time, device or inter-process work was found, "
                                      "so QNX would mostly run this code as it is.")
    reasons = [b.title for b in highs + mediums][:5]

    caveats: list[str] = []
    serious = [f for f in active if f.severity in ("blocker", "high")]
    if serious:
        caveats.append(f"Porting effort: {len(serious)} blocker/high finding(s) need code changes first "
                       "(see the Audit tab and the step-by-step guide).")
    if roles.isdisjoint({"periodic_control_loop", "device_service"}):
        caveats.append("No hard real-time loop or device I/O was detected, so QNX's timing strengths matter less "
                       "for this code.")
    if by_rule.keys() & {"LNX-SOCKETCAN", "LNX-I2C", "LNX-SPI"}:
        caveats.append("Hardware access depends on your board's QNX drivers: CAN, I2C and SPI interfaces differ "
                       "from Linux.")
    if not sysroot_verified:
        caveats.append("API availability has not been checked against your QNX SDP yet (see Setup).")
    caveats.append("These are capabilities QNX provides, not measurements. Use the Verify tab on a QNX target "
                   "before relying on timing.")
    return out, QnxFit(level=level, headline=headline, reasons=reasons, caveats=caveats)
