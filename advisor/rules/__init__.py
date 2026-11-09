"""Rule DB loading."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")
FEATURES_PATH = Path(__file__).with_name("features.yaml")
EXTRA_TOKENS = {"SCHED_FIFO", "SCHED_RR", "AF_UNIX", "AF_LOCAL", "PTHREAD_MUTEX_INITIALIZER",
                "PTHREAD_PRIO_INHERIT", "CPU_SET"}


@dataclass
class Rule:
    id: str
    title: str
    match: dict
    raw: dict = field(repr=False)

    @property
    def availability(self) -> dict | None:
        return self.raw.get("availability_check")

    @property
    def alternatives(self) -> list[dict]:
        return self.raw.get("qnx_alternatives", [])

    @property
    def feature_tags(self) -> list[str]:
        return self.raw.get("feature_tags", [])

    def all_apis(self) -> set[str]:
        return {a for alt in self.alternatives for a in alt.get("apis", [])}


@lru_cache(maxsize=1)
def load_rules() -> tuple[Rule, ...]:
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return tuple(Rule(id=r["id"], title=r.get("title", r["id"]), match=r.get("match", {}), raw=r) for r in data)


@lru_cache(maxsize=1)
def load_features() -> dict:
    return yaml.safe_load(FEATURES_PATH.read_text(encoding="utf-8"))


def ruleset_hash() -> str:
    h = hashlib.sha256(RULES_PATH.read_bytes() + FEATURES_PATH.read_bytes())
    return h.hexdigest()[:16]


def interesting_tokens() -> set[str]:
    toks = set(EXTRA_TOKENS)
    for r in load_rules():
        toks.update(r.match.get("tokens", []))
        toks.update(c for c in r.match.get("calls", []) if c.isupper() or c.startswith("PTHREAD_"))
    return toks


def config_globs() -> list[str]:
    return [g for r in load_rules() for g in r.match.get("files", [])]


def rules_db_identifiers() -> set[str]:
    """Every API named anywhere in the rule DB or feature catalogue (used by the guard)."""
    ids: set[str] = set()
    for r in load_rules():
        ids |= r.all_apis()
        ids |= set(r.match.get("calls", []))
    for f in load_features().values():
        ids |= set(f.get("apis", []))
    return ids
