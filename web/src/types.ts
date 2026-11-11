// Mirrors advisor/models.py (schema_version 2.0).
export type Severity = "blocker" | "high" | "medium" | "low" | "info";
export type EvidenceType = "measured" | "static" | "documented" | "qualitative";

export interface SourceLocation { file_path: string; line_start: number; line_end: number; snippet: string }
export interface Alternative { kind: string; apis: string[]; note: string }
export interface Finding {
  rule_id: string; title: string; severity: Severity;
  sysroot_status: "available" | "missing" | "unknown_no_sdp";
  locations: SourceLocation[]; already_guarded: boolean; guidance: string;
  alternatives: Alternative[]; link_libs: string[]; sysroot_detail: string;
}
export interface FeatureRecommendation {
  feature: string; apis: string[]; headers: string[]; target_component: string; rationale: string;
  relevance: number; diagram_mermaid: string | null; verified_in_sysroot: boolean;
}
export interface Improvement {
  dimension: string; current_limitation: string; evidence_locations: SourceLocation[];
  qnx_improvement: string; evidence_type: EvidenceType; measurement_ref: string | null;
}
export interface Step {
  n: number; title: string; category: string; affected_files: string[]; explanation: string;
  before_code: string | null; after_code: string | null; qcc_syntax_check: "passed" | "failed" | "skipped";
  verify_command: string; est_effort: "S" | "M" | "L";
}
export interface KitFile { path: string; description: string; content: string; qcc_compiled: string }
export interface VerificationRecord {
  id: string; binary_sha256: string; target_uname: string; sdp_version: string; target_kind: string;
  exit_status: number; metrics: Record<string, number>; timestamp_utc: string; note: string;
}
export interface IntegrationReport {
  schema_version: "2.0"; repo_url: string; commit_sha: string; mode: "M1" | "M2" | "M3";
  sdp_version: string | null; languages: string[]; build_systems: string[]; readiness_score: number | null; applicable?: boolean;
  summary: string; findings: Finding[]; pillar1_features: FeatureRecommendation[];
  pillar2_improvements: Improvement[]; pillar3_steps: Step[]; kit: KitFile[];
  verification: VerificationRecord[]; unverified_claims_removed: number; roles: string[];
  service_name: string; generated_at_utc: string; sysroot_verified: boolean;
}
export interface EnvInfo {
  mode: "M0" | "M1" | "M2" | "M3"; mode_reason: string; llm: string | null; tree_sitter: boolean;
  sdp: { path: string; version: string; archs: string[]; qcc_version: string } | null;
  index: { sdp_version: string; symbols: number; headers: number; created_utc: string } | null;
  target: { spec: string; reachable: boolean; detail: string } | null;
}
export interface JobEvent { event: string; data: Record<string, unknown> }

// ----- Setup page
export interface SetupCheck {
  id: string; label: string; status: "ok" | "warn" | "missing" | "optional"; detail: string; fix: string; required: boolean; action?: string;
}
export interface ProviderInfo {
  id: string; label: string; key_env: string; model_env: string; default_model: string; key_url: string; key_hint: string; blurb: string;
}
export interface LlmTest { ok: boolean; message: string; latency_ms?: number; tested_utc?: string; provider?: string; model?: string }
export interface LlmStatus {
  providers: ProviderInfo[];
  active: null | {
    provider: string; label: string; model: string; default_model: string; key_masked: string;
    source: "settings" | "environment"; key_env: string; last_test: LlmTest | null;
  };
}
export interface SetupInfo { checks: SetupCheck[]; llm: LlmStatus }
