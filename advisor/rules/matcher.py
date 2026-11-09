"""Match scan hits against the rule DB and decide severity from the local sysroot index."""
from __future__ import annotations

import fnmatch
import re

from ..models import Alternative, Finding, SourceLocation
from ..scanner import Hit, ScanResult
from ..sdp.indexer import SysrootIndex
from . import Rule, load_rules

MAX_LOCATIONS = 25
_NULL_ATTR = re.compile(r",\s*(NULL|0|nullptr)\s*\)\s*$")


def _is_token_name(name: str) -> bool:
    return name.isupper() or name.startswith("PTHREAD_") or name.startswith("CPU_")


def _rule_hits(rule: Rule, sr: ScanResult) -> list[Hit]:
    m = rule.match
    hits: list[Hit] = []
    includes = set(m.get("includes", []))
    calls = {c for c in m.get("calls", []) if not _is_token_name(c)}
    tokens = set(m.get("tokens", [])) | {c for c in m.get("calls", []) if _is_token_name(c)}
    string_res = [re.compile(s) for s in m.get("strings", [])]
    for h in sr.hits:
        if h.kind == "include" and h.name in includes:
            hits.append(h)
        elif h.kind == "call" and (h.name in calls or h.name in tokens):
            hits.append(h)
        elif h.kind == "token" and h.name in tokens:
            hits.append(h)
        elif h.kind == "string" and any(r.search(h.name) for r in string_res):
            hits.append(h)
    for lib in m.get("link_libs", []):
        hits.extend(sr.build.link_libs.get(lib, []))
    flag_res = [re.compile(f) for f in m.get("build_flags", [])]
    if flag_res:
        hits.extend(h for h in sr.build.flag_lines if any(r.search(h.name) for r in flag_res))
    for g in m.get("files", []):
        hits.extend(h for h in sr.config_hits if h.kind == "file" and fnmatch.fnmatch(h.name, g))
    return _apply_condition(m.get("condition"), hits, sr)


def _apply_condition(cond: str | None, hits: list[Hit], sr: ScanResult) -> list[Hit]:
    if not cond:
        return hits
    if cond == "periodic_sleep_loop":
        return [h for h in hits if h.in_loop]
    if cond == "socket_lib_not_linked":
        if "socket" in sr.build.link_libs or sr.build.find_packages & {"socket"}:
            return []
        return hits
    if cond == "requires_root":
        extra = [h for h in sr.hits if h.kind == "call" and h.name in ("geteuid", "getuid")
                 and re.search(r"(!=|==)\s*0\b|\b0\s*(!=|==)", h.snippet)]
        extra += [h for h in sr.config_hits if h.kind == "config_root"]
        return hits + extra
    if cond == "default_mutex_mixed_priority":
        mixed = sr.has_call("pthread_create") and (
            sr.has_token("SCHED_FIFO", "SCHED_RR") or sr.has_call("pthread_setschedparam", "sched_setscheduler")
            or any(h.kind == "config_rt" for h in sr.config_hits))
        if not mixed:
            return []
        out = []
        for h in hits:
            if h.name == "pthread_mutex_init" and h.kind == "call":
                if _NULL_ATTR.search(h.args.strip()):
                    out.append(h)
            elif h.name == "PTHREAD_MUTEX_INITIALIZER":
                out.append(h)
        return out
    if cond == "rt_thread_with_workers":
        return hits if sr.has_call("pthread_create") else []
    raise ValueError(f"unknown rule condition {cond}")


def _locations(hits: list[Hit]) -> list[SourceLocation]:
    seen, out = set(), []
    for h in sorted(hits, key=lambda h: (h.file, h.line)):
        key = (h.file, h.line)
        if key in seen:
            continue
        seen.add(key)
        out.append(SourceLocation(file_path=h.file, line_start=h.line, line_end=h.line, snippet=h.snippet[:2000]))
        if len(out) >= MAX_LOCATIONS:
            break
    return out


def _availability(rule: Rule, hits: list[Hit], idx: SysrootIndex | None):
    """Returns (status, detail, link_libs, hits_to_keep) or None to suppress the finding."""
    chk = rule.availability
    raw = rule.raw
    link_libs: list[str] = []
    if chk is None:
        return ("available" if idx else "unknown_no_sdp"), "", link_libs, hits
    if idx is None:
        status = "unknown_no_sdp"
        if raw.get("expected_lib"):
            link_libs = [raw["expected_lib"]]
        return status, f"No SDP index: assumed {raw.get('expected_on_qnx', 'unknown')} on QNX 8.0 (unverified)", link_libs, hits

    if "libraries" in chk:
        matched = sorted({h.name for h in hits if h.kind == "link_lib"})
        missing = [lib for lib in matched if not idx.has_library(lib)]
        if not missing:
            return "available", "present in sysroot: " + ", ".join(f"lib{x}" for x in matched), [], hits
        keep = [h for h in hits if h.kind != "link_lib" or h.name in missing]
        return "missing", "not in sysroot lib dirs: " + ", ".join(f"lib{x}" for x in missing) + " (provided by libc on QNX)", [], keep

    details, ok = [], True
    for s in chk.get("symbols", []):
        lib = idx.lib_for(s)
        if lib is None:
            ok = False
            details.append(f"{s}: not exported by any sysroot library")
        else:
            details.append(f"{s}: lib{lib}")
            if lib != "c":
                link_libs.append(lib)
    for hdr in chk.get("headers", []):
        if idx.has_header(hdr):
            details.append(f"<{hdr}> present")
        else:
            ok = False
            details.append(f"<{hdr}> not in sysroot")
    if rule.id == "LNX-SOCKLIB" and ok and not link_libs:
        return None                                   # socket() is in libc on this SDP: nothing to do
    return ("available" if ok else "missing"), "; ".join(details), sorted(set(link_libs)), hits


def match_rules(sr: ScanResult, idx: SysrootIndex | None) -> list[Finding]:
    findings: list[Finding] = []
    for rule in load_rules():
        hits = _rule_hits(rule, sr)
        if not hits:
            continue
        av = _availability(rule, hits, idx)
        if av is None:
            continue
        status, detail, link_libs, hits = av
        raw = rule.raw
        if rule.availability is not None:
            effective = status
            if status == "unknown_no_sdp":
                effective = raw.get("expected_on_qnx", "missing")
            severity = raw["severity_if_available"] if effective == "available" else raw["severity_if_missing"]
        else:
            severity = raw.get("severity", "medium")
        findings.append(Finding(
            rule_id=rule.id,
            title=rule.title,
            severity=severity,
            sysroot_status=status,
            locations=_locations(hits),
            already_guarded=all(h.guarded for h in hits),
            guidance=" ".join(raw.get("guidance", "").split()),
            alternatives=[Alternative(kind=a["kind"], apis=a.get("apis", []), note=a.get("note", ""))
                          for a in rule.alternatives],
            link_libs=link_libs,
            sysroot_detail=detail,
        ))
    order = {"blocker": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (order[f.severity], f.rule_id))
    return findings
