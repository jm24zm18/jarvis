export interface ThreadItem {
  id: string;
  status: string;
  channel_type: string;
  created_at: string;
  updated_at: string;
  last_message?: string | null;
}

export interface MediaAttachment {
  id: string;
  url: string;
  mime_type: string;
  thumbnail_url?: string | null;
  size_bytes: number;
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant" | string;
  speaker?: string;
  content: string;
  created_at: string;
  media?: MediaAttachment[];
}

export interface OnboardingStatus {
  status: "required" | "in_progress" | "completed" | "not_required";
  required: boolean;
  current_step?: number;
  total_steps?: number;
  question?: string | null;
}

export interface SystemStatus {
  time: string;
  system: { lockdown: number; restarting: number };
  providers: {
    primary: boolean;
    fallback: boolean;
    primary_name?: string;
    fallback_name?: string;
  };
  provider_errors?: {
    last_primary_failure?: {
      reason: string;
      at: string;
    } | null;
  };
  queue_depths: Record<string, number>;
  scheduler: {
    dispatchable_total?: number;
    deferred_total?: number;
    schedule_count?: number;
    schedules?: Array<Record<string, unknown>>;
  };
}

export interface AgentSummary {
  id: string;
  description: string;
  tool_count: number;
}

export interface AgentDetail {
  id: string;
  identity_md: string;
  soul_md: string;
  heartbeat_md: string;
  permissions: Array<{ tool_name: string; effect: string }>;
}

export interface EventItem {
  id: string;
  trace_id?: string;
  span_id?: string;
  parent_span_id?: string | null;
  thread_id?: string | null;
  event_type: string;
  component: string;
  actor_type: string;
  actor_id: string;
  payload?: Record<string, unknown>;
  payload_redacted_json?: string;
  created_at: string;
}

export interface MemoryItem {
  id: string;
  thread_id?: string;
  text: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

export interface MemoryStats {
  total_items: number;
  embedded_items: number;
  embedding_coverage_pct: number;
}

export interface MemoryConsistencyReportItem {
  id: string;
  thread_id: string;
  sample_size: number;
  total_items: number;
  conflicted_items: number;
  consistency_score: number;
  details: Record<string, unknown>;
  created_at: string;
}

export interface MemoryFailureItem {
  id: string;
  trace_id: string;
  phase: string;
  summary: string;
  details_json: string;
  attempt: number;
  created_at: string;
}

export interface MemoryReviewItem {
  id: string;
  uid: string;
  thread_id: string;
  agent_id: string;
  reason: string;
  status: string;
  reviewer_id?: string | null;
  resolution?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryGraphEdge {
  source_uid: string;
  target_uid: string;
  relation_type: string;
  depth: number;
}

export interface MemoryGraph {
  root_uid: string;
  nodes: string[];
  edges: MemoryGraphEdge[];
}

export interface MemoryStateStats {
  tiers: Array<{ tier: string; count: number }>;
  archive_items: number;
  open_conflicts: number;
}

export interface ScheduleItem {
  id: string;
  thread_id?: string | null;
  cron_expr: string;
  payload_json: string;
  enabled: boolean;
  last_run_at?: string | null;
  created_at: string;
  max_catchup?: number | null;
}

export interface DispatchItem {
  schedule_id: string;
  due_at: string;
  dispatched_at: string;
}

export interface PatchItem {
  trace_id: string;
  state: string;
  detail: string;
}

export interface PatchDetail extends PatchItem {
  diff: string;
}

export interface PermissionGroup {
  principal_id: string;
  principal_type: string;
  tools: Record<string, string>;
}

export interface ProviderConfig {
  primary_provider: "openrouter" | "sglang" | "lmstudio" | string;
  fallback_provider: "openrouter" | "sglang" | "lmstudio" | string;
  openrouter_model: string;
  sglang_model: string;
  lmstudio_model: string;
  lmstudio_base_url: string;
  openrouter_api_key_set: boolean;
  openrouter_api_key_masked: string;
  lmstudio_api_key_set: boolean;
  lmstudio_api_key_masked: string;
  available_primary_providers: string[];
  available_fallback_providers: string[];
}

export interface ProviderModelsCatalog {
  sglang_models: string[];
  lmstudio_models: string[];
  sglang_source: string;
  lmstudio_source: string;
}

export interface ProviderConfigUpdateResult {
  ok: boolean;
  updated: string[];
  primary_provider: "openrouter" | "sglang" | "lmstudio" | string;
  fallback_provider: "openrouter" | "sglang" | "lmstudio" | string;
  openrouter_model: string;
  sglang_model: string;
  lmstudio_model: string;
  lmstudio_base_url: string;
  openrouter_api_key_set: boolean;
  openrouter_api_key_masked: string;
  lmstudio_api_key_set: boolean;
  lmstudio_api_key_masked: string;
  api_reloaded: boolean;
  worker_reload_enqueued: boolean;
}

export interface BugReport {
  id: string;
  title: string;
  description: string;
  status: "open" | "in_progress" | "resolved" | "closed";
  priority: "low" | "medium" | "high" | "critical";
  reporter_id?: string | null;
  assignee_agent?: string | null;
  thread_id?: string | null;
  trace_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeatureRequest extends BugReport {
  approval_status: "pending" | "approved" | "rejected";
  approval_note?: string;
  approved_by?: string | null;
  approved_at?: string | null;
  rejected_by?: string | null;
  rejected_at?: string | null;
}

export interface FeatureBuildRun {
  id: string;
  feature_id: string;
  trace_id: string;
  thread_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "timed_out" | "cancelled" | "decomposed";
  summary: string;
  attempt_count: number;
  max_attempts: number;
  retry_state: "none" | "scheduled" | "running" | "exhausted";
  next_retry_at: string;
  last_failure_reason: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ApprovalRecord {
  id: string;
  action: string;
  actor_id: string;
  status: "approved" | "consumed" | "revoked";
  target_ref: string;
  expires_at: string | null;
  consumed_by_trace_id: string;
  created_at: string;
}

export interface ChannelReplyApprovalRequest {
  id: string;
  source_thread_id: string;
  source_message_id: string;
  trace_id: string;
  channel_type: string;
  recipient: string;
  status: string;
  decision_mode: string;
  reason: string;
  admin_thread_id: string;
  decided_by: string;
  decided_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChannelReplyPermission {
  id: string;
  channel_type: string;
  recipient: string;
  status: string;
  granted_by: string;
  revoked_by: string;
  revoked_reason: string;
  created_at: string;
  updated_at: string;
  revoked_at?: string | null;
}

export interface RepoStatus {
  branch: string;
  upstream: string;
  ahead: number;
  behind: number;
  staged: string[];
  unstaged: string[];
  untracked: string[];
  conflicted: string[];
  is_clean: boolean;
}

export interface RepoCommit {
  sha: string;
  short_sha: string;
  subject: string;
  author_name: string;
  author_email: string;
  authored_at: string;
}

export interface RepoBranchSet {
  current: string;
  local: string[];
  remote: string[];
}

export interface FitnessSnapshot {
  id: string;
  period_start: string;
  period_end: string;
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface GovernanceSlo {
  status: "safe" | "degraded" | "blocked" | string;
  reasons: string[];
  thresholds: Record<string, unknown>;
  snapshot: FitnessSnapshot | null;
  detail: Record<string, unknown>;
}

export interface GovernanceSloHistoryItem {
  snapshot_id: string;
  created_at: string;
  status: string;
  reasons: string[];
  detail: Record<string, unknown>;
}

export interface EvolutionItem {
  id: string;
  item_id: string;
  trace_id: string;
  span_id: string;
  thread_id?: string | null;
  status: string;
  evidence_refs?: string[];
  result?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  updated_by: string;
}
