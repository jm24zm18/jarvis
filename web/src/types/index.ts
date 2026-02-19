export interface ThreadItem {
  id: string;
  status: string;
  channel_type: string;
  created_at: string;
  updated_at: string;
  last_message?: string | null;
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant" | string;
  speaker?: string;
  content: string;
  created_at: string;
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

export interface GoogleOAuthConfig {
  configured: boolean;
  has_client_credentials: boolean;
  token_cache_exists: boolean;
  has_refresh_token: boolean;
  auto_refresh_enabled: boolean;
  access_expires_at_ms: number;
  seconds_until_access_expiry: number;
  current_tier_id: string;
  current_tier_name: string;
  quota_blocked: boolean;
  quota_block_seconds_remaining: number;
  quota_block_reason: string;
}

export interface GoogleOAuthStartResult {
  state: string;
  auth_url: string;
  redirect_uri: string;
  client_id_source: string;
}

export interface GoogleOAuthStatus {
  status: string;
  detail: string;
}

export interface ProviderConfig {
  primary_provider: "gemini" | "sglang" | string;
  gemini_model: string;
  sglang_model: string;
  available_primary_providers: string[];
}

export interface ProviderModelsCatalog {
  gemini_models: string[];
  gemini_verified_models: string[];
  gemini_verification: Record<string, string>;
  sglang_models: string[];
  gemini_source: string;
  sglang_source: string;
}

export interface ProviderConfigUpdateResult {
  ok: boolean;
  updated: string[];
  primary_provider: "gemini" | "sglang" | string;
  gemini_model: string;
  sglang_model: string;
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
