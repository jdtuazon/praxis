// Mirrors praxis.models.ExecutionReport (model_dump mode="json").

export type ExecStatus = "success" | "partial" | "failed" | "rolled_back";
export type StepStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "skipped"
  | "rolled_back";

export interface CallAttribution {
  kind: string;
  ref: string;
  detail: string;
}

export interface StepReport {
  index: number;
  intent: string;
  capability: string | null;
  status: StepStatus;
  attempts: number;
  duration_s: number;
  api_calls: number;
  wasted_calls: number;
  result_summary: string | null;
  result_url: string | null;
  result_detail: string | null;
  error: string | null;
  rolled_back: boolean;
  prevalidated: boolean;
  provenance: CallAttribution[];
  inserted_by_constraint: string | null;
}

export interface Decision {
  summary: string;
  rationale: string;
  stage: string;
}

export interface TestOutcome {
  tier: string;
  passed: boolean;
  detail: string;
  api_calls: number;
}

export interface SynthesisAttempt {
  attempt: number;
  outcomes: TestOutcome[];
  error: string | null;
}

export interface SynthesisResult {
  requested_for: string;
  success: boolean;
  capability_name: string | null;
  attempts: SynthesisAttempt[];
  final_error: string | null;
  api_calls: number;
  llm_calls: number;
}

export interface Learning {
  instruction_signature: string;
  mode: string;
  run_number: number;
  is_repeat: boolean;
  api_calls: number;
  llm_calls: number;
  duration_s: number;
  wasted_calls: number;
  failed_steps: number;
  synthesized: number;
  baseline_api_calls: number | null;
  baseline_llm_calls: number | null;
  baseline_wasted_calls: number | null;
  baseline_duration_s: number | null;
  api_calls_saved: number;
  llm_calls_saved: number;
  wasted_calls_saved: number;
  speedup_pct: number | null;
  attributions: string[];
}

export interface MemorySnapshot {
  counts: { instructions: number; executions: number; capabilities: number; constraints: number };
  capability_names: string[];
  constraint_keys: string[];
}

export interface MemoryDiff {
  new_capabilities: string[];
  new_constraints: string[];
  updated_stats: string[];
  lines: string[];
}

export interface Plan {
  instruction: string;
  source: string;
  intent_signature: string;
  rationale: string;
  confidence: number;
  steps: { index: number; intent: string; capability: string | null; inserted_by_constraint: string | null }[];
}

export interface ExecutionReport {
  execution_id: number | null;
  instruction: string;
  status: ExecStatus;
  duration_s: number;
  total_api_calls: number;
  total_llm_calls: number;
  total_tokens: number;
  wasted_calls: number;
  plan: Plan;
  steps: StepReport[];
  decisions: Decision[];
  synthesis: SynthesisResult[];
  synthesized_capabilities: string[];
  discovered_constraints: string[];
  confidence: number;
  confidence_notes: string[];
  rollback_performed: boolean;
  rollback_steps: string[];
  manual_cleanup_required: string[];
  memory_before: MemorySnapshot;
  memory_after: MemorySnapshot;
  memory_diff: MemoryDiff;
  learning: Learning;
  summary: string;
}

export interface CapabilityInfo {
  name: string;
  kind: string;
  source: string;
  status: string;
  attempts: number;
  success_rate: number | null;
  description: string;
}

export interface ConstraintInfo {
  kind: string;
  origin: string;
  scope: string;
  key: string;
  value: unknown;
  rewrites_plan: boolean;
  hits: number;
  description: string;
}

export interface MemoryState {
  counts: { instructions: number; executions: number; capabilities: number; constraints: number };
  capabilities: CapabilityInfo[];
  constraints: ConstraintInfo[];
}

export interface BenchRow {
  status: string;
  api_calls: number;
  llm_calls: number;
  wasted_calls: number;
  synthesized: number;
  saved: string[];
}

export interface BenchResult {
  workflow_rule: { cold: BenchRow; warm: BenchRow; control_after_wipe: BenchRow };
  synthesis_transfer: { cold: BenchRow; transfer: BenchRow };
}

export interface Meta {
  mode: "offline" | "live";
  platform: string;
  llm_ready: boolean;
  platform_ready: boolean;
}

export interface Example {
  label: string;
  instruction: string;
}
