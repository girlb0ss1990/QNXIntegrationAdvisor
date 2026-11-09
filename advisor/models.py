"""Report schema (spec section 7). Pydantic models shared by CLI, server and web UI."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

EvidenceType = Literal["measured", "static", "documented", "qualitative"]
Severity = Literal["blocker", "high", "medium", "low", "info"]
SysrootStatus = Literal["available", "missing", "unknown_no_sdp"]

FeatureName = Literal[
    "resource_manager", "channels_pulses", "priority_inheritance",
    "sporadic_scheduling", "cpu_time_budget_monitoring", "runmask_affinity",
    "ham", "procmgr_ability", "secpol", "typed_shared_memory",
    "slog2", "tracelogger", "hypervisor",
]


class SourceLocation(BaseModel):
    file_path: str
    line_start: int
    line_end: int
    snippet: str = Field(default="", max_length=2000)


class Alternative(BaseModel):
    kind: Literal["posix", "qnx_native", "build", "design"]
    apis: list[str] = []
    note: str = ""


class Finding(BaseModel):
    rule_id: str
    title: str = ""
    severity: Severity
    sysroot_status: SysrootStatus
    locations: list[SourceLocation]
    already_guarded: bool = False         # every hit sits inside an existing __QNX__/__QNXNTO__ guard
    guidance: str = ""
    alternatives: list[Alternative] = []
    link_libs: list[str] = []             # e.g. ["fsnotify"] for inotify
    sysroot_detail: str = ""              # e.g. "inotify_add_watch found in libfsnotify.so"


class FeatureRecommendation(BaseModel):          # Pillar 1
    feature: FeatureName
    apis: list[str]
    headers: list[str] = []
    target_component: str
    rationale: str
    relevance: int = Field(ge=1, le=5)
    diagram_mermaid: Optional[str] = None
    verified_in_sysroot: bool = False


class Improvement(BaseModel):                     # Pillar 2
    dimension: Literal["determinism_latency", "fault_isolation_recovery",
                       "ipc_efficiency", "security_least_privilege", "maintainability_portability"]
    current_limitation: str
    evidence_locations: list[SourceLocation] = []
    qnx_improvement: str
    evidence_type: EvidenceType
    measurement_ref: Optional[str] = None


class Step(BaseModel):                            # Pillar 3
    n: int
    title: str
    category: Literal["toolchain_build", "api_migration", "resmgr_conversion",
                      "scheduling_timing", "reliability_security", "deploy_verify"]
    affected_files: list[str] = []
    explanation: str
    before_code: Optional[str] = None
    after_code: Optional[str] = None
    qcc_syntax_check: Literal["passed", "failed", "skipped"] = "skipped"
    verify_command: str
    est_effort: Literal["S", "M", "L"]


class KitFile(BaseModel):
    path: str
    description: str
    content: str
    qcc_compiled: Literal["x86_64", "aarch64le", "both", "not_applicable", "skipped", "failed"] = "skipped"


class VerificationRecord(BaseModel):
    id: str
    binary_sha256: str
    target_uname: str
    sdp_version: str
    target_kind: Literal["qemu_x86_64", "qemu_aarch64le", "rpi5", "other"]
    exit_status: int
    metrics: dict[str, float] = {}
    timestamp_utc: str
    note: str = ""


class IntegrationReport(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    repo_url: str
    commit_sha: str
    mode: Literal["M1", "M2", "M3"]
    sdp_version: Optional[str] = None
    languages: list[str] = []
    build_systems: list[str] = []
    readiness_score: int = Field(ge=0, le=100)
    summary: str
    findings: list[Finding] = []
    pillar1_features: list[FeatureRecommendation] = []
    pillar2_improvements: list[Improvement] = []
    pillar3_steps: list[Step] = []
    kit: list[KitFile] = []
    verification: list[VerificationRecord] = []
    unverified_claims_removed: int = 0
    roles: list[str] = []                 # role heuristics (device_service, periodic_control_loop, ...)
    service_name: str = "service"
    generated_at_utc: str = ""
    sysroot_verified: bool = False
