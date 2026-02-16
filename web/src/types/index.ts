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
  providers: { primary: boolean; fallback: boolean };
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
  created_at?: string;
}

export interface MemoryStats {
  total_items: number;
  embedded_items: number;
  embedding_coverage_pct: number;
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
