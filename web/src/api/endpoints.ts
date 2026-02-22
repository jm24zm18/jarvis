import { apiFetch } from "./client";
import type {
  AgentDetail,
  AgentSummary,
  ApprovalRecord,
  BugReport,
  DispatchItem,
  EventItem,
  FeatureBuildRun,
  MemoryItem,
  MemoryConsistencyReportItem,
  MemoryFailureItem,
  MemoryReviewItem,
  MemoryGraph,
  MemoryStateStats,
  MemoryStats,
  MessageItem,
  PatchDetail,
  PatchItem,
  PermissionGroup,
  ScheduleItem,
  SystemStatus,
  ThreadItem,
  OnboardingStatus,
  GoogleOAuthConfig,
  ProviderConfig,
  ProviderModelsCatalog,
  ProviderConfigUpdateResult,
  GoogleOAuthStartResult,
  GoogleOAuthStatus,
  FitnessSnapshot,
  GovernanceSlo,
  GovernanceSloHistoryItem,
  EvolutionItem,
  FeatureRequest,
  RepoStatus,
  RepoCommit,
  RepoBranchSet,
} from "../types";

export const login = (password: string) =>
  apiFetch<{ session_id: string; user_id: string; role: string }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });

export const me = () => apiFetch<{ user_id: string }>("/api/v1/auth/me");
export const logout = () => apiFetch<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });

export const listThreads = (all = false) =>
  apiFetch<{ items: ThreadItem[] }>(`/api/v1/threads${all ? "?all=true" : ""}`);

export const getThread = (threadId: string) =>
  apiFetch<{
    id: string;
    status: string;
    channel_type: string;
    created_at: string;
    updated_at: string;
    settings: { verbose: boolean; active_agent_ids: string[] };
  }>(`/api/v1/threads/${threadId}`);

export const patchThread = (
  threadId: string,
  payload: Partial<{ status: string; verbose: boolean; active_agent_ids: string[] }>,
) =>
  apiFetch<{ ok: boolean }>(`/api/v1/threads/${threadId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const createThread = () =>
  apiFetch<{ id: string }>("/api/v1/threads", { method: "POST", body: "{}" });

export const listMessages = (threadId: string, before?: string) =>
  apiFetch<{ items: MessageItem[]; next_before?: string }>(
    `/api/v1/threads/${threadId}/messages${before ? `?before=${encodeURIComponent(before)}` : ""}`,
  );

export const sendMessage = (threadId: string, content: string) =>
  apiFetch<{ ok: boolean; message_id: string; onboarding: boolean; trace_id?: string }>(
    `/api/v1/threads/${threadId}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ content }),
    },
  );

export const getOnboardingStatus = (threadId: string) =>
  apiFetch<OnboardingStatus>(`/api/v1/threads/${threadId}/onboarding`);

export const startOnboarding = (threadId: string) =>
  apiFetch<{ ok: boolean; prompted: boolean; message_id?: string | null }>(
    `/api/v1/threads/${threadId}/onboarding/start`,
    {
      method: "POST",
      body: "{}",
    },
  );

export const getSystemStatus = () => apiFetch<SystemStatus>("/api/v1/system/status");

export const setLockdown = (lockdown: boolean, reason = "manual") =>
  apiFetch<{ ok: boolean; system: { lockdown: number; restarting: number } }>(
    "/api/v1/system/lockdown",
    {
      method: "POST",
      body: JSON.stringify({ lockdown, reason }),
    },
  );

export const resetDatabase = () =>
  apiFetch<{ ok: boolean }>("/api/v1/system/reset-db", {
    method: "POST",
    body: "{}",
  });

export const reloadAgents = () =>
  apiFetch<{ ok: boolean }>("/api/v1/system/reload-agents", {
    method: "POST",
    body: "{}",
  });

export const listAgents = () => apiFetch<{ items: AgentSummary[] }>("/api/v1/agents");
export const getAgent = (agentId: string) => apiFetch<AgentDetail>(`/api/v1/agents/${agentId}`);

export const listEvents = (params: {
  event_type?: string;
  component?: string;
  thread_id?: string;
  query?: string;
}) => {
  const qs = new URLSearchParams();
  if (params.event_type) qs.set("event_type", params.event_type);
  if (params.component) qs.set("component", params.component);
  if (params.thread_id) qs.set("thread_id", params.thread_id);
  if (params.query) qs.set("query", params.query);
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<{ items: EventItem[] }>(`/api/v1/events${suffix}`);
};

export const getTrace = (traceId: string, view: "redacted" | "raw" = "redacted") =>
  apiFetch<{ trace_id: string; view: "redacted" | "raw"; items: EventItem[] }>(
    `/api/v1/traces/${traceId}?view=${view}`,
  );

export const listMemory = (q = "", threadId = "") => {
  const qs = new URLSearchParams();
  if (q.trim()) qs.set("q", q.trim());
  if (threadId.trim()) qs.set("thread_id", threadId.trim());
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<{ items: MemoryItem[] }>(`/api/v1/memory${suffix}`);
};

export const memoryStats = () => apiFetch<MemoryStats>("/api/v1/memory/stats");

export const listSchedules = () => apiFetch<{ items: ScheduleItem[] }>("/api/v1/schedules");

export const createSchedule = (payload: {
  thread_id?: string;
  cron_expr: string;
  payload_json: string;
  max_catchup?: number;
}) =>
  apiFetch<{ id: string }>("/api/v1/schedules", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateSchedule = (scheduleId: string, payload: Record<string, unknown>) =>
  apiFetch<{ ok: boolean }>(`/api/v1/schedules/${scheduleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const listDispatches = (scheduleId: string) =>
  apiFetch<{ items: DispatchItem[] }>(`/api/v1/schedules/${scheduleId}/dispatches`);

export const listPatches = () => apiFetch<{ items: PatchItem[] }>("/api/v1/selfupdate/patches");
export const getPatch = (traceId: string) =>
  apiFetch<PatchDetail>(`/api/v1/selfupdate/patches/${traceId}`);

export const approvePatch = (traceId: string) =>
  apiFetch<{ approval_id: string; action: string }>(`/api/v1/selfupdate/patches/${traceId}/approve`, {
    method: "POST",
    body: "{}",
  });

export const patchChecks = (traceId: string) =>
  apiFetch<{ trace_id: string; items: Array<Record<string, unknown>> }>(
    `/api/v1/selfupdate/patches/${traceId}/checks`,
  );

export const patchTimeline = (traceId: string) =>
  apiFetch<{
    trace_id: string;
    transitions: Array<Record<string, unknown>>;
    checks: Array<Record<string, unknown>>;
  }>(`/api/v1/selfupdate/patches/${traceId}/timeline`);

export const listPermissions = () =>
  apiFetch<{ items: PermissionGroup[] }>("/api/v1/permissions");

export const allowPermission = (principalId: string, toolName: string) =>
  apiFetch<{ ok: boolean }>(`/api/v1/permissions/${principalId}/${toolName}`, {
    method: "PUT",
    body: "{}",
  });

export const deletePermission = (principalId: string, toolName: string) =>
  apiFetch<{ ok: boolean }>(`/api/v1/permissions/${principalId}/${toolName}`, {
    method: "DELETE",
  });

export const getGoogleOAuthConfig = () =>
  apiFetch<GoogleOAuthConfig>("/api/v1/auth/google/config");

export const startGoogleOAuth = (payload: {
  client_id?: string;
  client_secret?: string;
  redirect_uri?: string;
}) =>
  apiFetch<GoogleOAuthStartResult>("/api/v1/auth/google/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getGoogleOAuthStatus = (state: string) =>
  apiFetch<GoogleOAuthStatus>(`/api/v1/auth/google/status?state=${encodeURIComponent(state)}`);

export const getProviderConfig = () =>
  apiFetch<ProviderConfig>("/api/v1/auth/providers/config");

export const getProviderModelsCatalog = () =>
  apiFetch<ProviderModelsCatalog>("/api/v1/auth/providers/models");

export const updateProviderConfig = (payload: {
  primary_provider?: "gemini" | "sglang" | string;
  gemini_model?: string;
  sglang_model?: string;
}) =>
  apiFetch<ProviderConfigUpdateResult>("/api/v1/auth/providers/config", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listBugs = (params: {
  status?: string;
  priority?: string;
  search?: string;
}) => {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.priority) qs.set("priority", params.priority);
  if (params.search) qs.set("search", params.search);
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<{ items: BugReport[]; total: number }>(`/api/v1/bugs${suffix}`);
};

export const listFeatureRequests = (params?: {
  status?: string;
  priority?: string;
  approval_status?: string;
  search?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.priority) qs.set("priority", params.priority);
  if (params?.approval_status) qs.set("approval_status", params.approval_status);
  if (params?.search) qs.set("search", params.search);
  if (typeof params?.limit === "number") qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<{ items: FeatureRequest[]; total: number }>(`/api/v1/feature-requests${suffix}`);
};

export const createBug = (payload: {
  title: string;
  description: string;
  priority: string;
  thread_id?: string;
  trace_id?: string;
}) =>
  apiFetch<{ id: string }>("/api/v1/bugs", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const createFeatureRequest = (payload: {
  title: string;
  description: string;
  priority: string;
  thread_id?: string;
  trace_id?: string;
}) =>
  apiFetch<{ id: string }>("/api/v1/feature-requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateBug = (bugId: string, payload: Record<string, unknown>) =>
  apiFetch<{ ok: boolean }>(`/api/v1/bugs/${bugId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const deleteBug = (bugId: string) =>
  apiFetch<{ ok: boolean }>(`/api/v1/bugs/${bugId}`, {
    method: "DELETE",
  });

export const latestFitness = () =>
  apiFetch<{ item: FitnessSnapshot | null }>("/api/v1/governance/fitness/latest");

export const fitnessHistory = (limit = 12) =>
  apiFetch<{ items: FitnessSnapshot[]; limit: number }>(
    `/api/v1/governance/fitness/history?limit=${encodeURIComponent(String(limit))}`,
  );

export const dependencyStewardStatus = () =>
  apiFetch<Record<string, unknown>>("/api/v1/governance/dependency-steward");

export const releaseCandidateStatus = () =>
  apiFetch<Record<string, unknown>>("/api/v1/governance/release-candidate");

export const governanceDecisionTimeline = (params: {
  trace_id?: string;
  thread_id?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params.trace_id) qs.set("trace_id", params.trace_id);
  if (params.thread_id) qs.set("thread_id", params.thread_id);
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<Record<string, unknown>>(`/api/v1/governance/decision-timeline${suffix}`);
};

export const governancePatchLifecycle = (traceId: string) =>
  apiFetch<Record<string, unknown>>(`/api/v1/governance/patch-lifecycle/${encodeURIComponent(traceId)}`);

export const governanceEvolutionItems = (params?: {
  status?: string;
  trace_id?: string;
  thread_id?: string;
  from?: string;
  to?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.trace_id) qs.set("trace_id", params.trace_id);
  if (params?.thread_id) qs.set("thread_id", params.thread_id);
  if (params?.from) qs.set("from", params.from);
  if (params?.to) qs.set("to", params.to);
  if (typeof params?.limit === "number") qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<{ items: EvolutionItem[]; filters: Record<string, unknown> }>(
    `/api/v1/governance/evolution/items${suffix}`,
  );
};

export const governanceLearningLoop = (windowDays = 14, refresh = true) =>
  apiFetch<Record<string, unknown>>(
    `/api/v1/governance/learning-loop?window_days=${encodeURIComponent(String(windowDays))}&refresh=${refresh ? "true" : "false"}`,
  );

export const governanceSlo = () =>
  apiFetch<GovernanceSlo>("/api/v1/governance/slo");

export const governanceSloHistory = (limit = 12) =>
  apiFetch<{ items: GovernanceSloHistoryItem[]; thresholds: Record<string, unknown>; limit: number }>(
    `/api/v1/governance/slo/history?limit=${encodeURIComponent(String(limit))}`,
  );

export const governanceRemediationFeedback = (remediationId: string, feedback: "accepted" | "rejected") =>
  apiFetch<Record<string, unknown>>(`/api/v1/governance/remediations/${encodeURIComponent(remediationId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({ feedback }),
  });

export const runMemoryMaintenance = () =>
  apiFetch<Record<string, unknown>>("/api/v1/memory/maintenance/run", {
    method: "POST",
    body: "{}",
  });

export const memoryConsistencyReport = (params?: {
  limit?: number;
  thread_id?: string;
  from_ts?: string;
  to_ts?: string;
}) => {
  const qs = new URLSearchParams();
  if (typeof params?.limit === "number") qs.set("limit", String(params.limit));
  if (params?.thread_id) qs.set("thread_id", params.thread_id);
  if (params?.from_ts) qs.set("from_ts", params.from_ts);
  if (params?.to_ts) qs.set("to_ts", params.to_ts);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<{ items: MemoryConsistencyReportItem[]; avg_consistency: number }>(
    `/api/v1/memory/state/consistency/report${suffix}`,
  );
};

export const memoryStateFailures = (params?: { similar_to?: string; k?: number }) => {
  const qs = new URLSearchParams();
  if (params?.similar_to) qs.set("similar_to", params.similar_to);
  if (typeof params?.k === "number") qs.set("k", String(params.k));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<{ items: MemoryFailureItem[] }>(`/api/v1/memory/state/failures${suffix}`);
};

export const memoryReviewConflicts = (limit = 50) =>
  apiFetch<{ items: MemoryReviewItem[] }>(
    `/api/v1/memory/state/review/conflicts?limit=${encodeURIComponent(String(limit))}`,
  );

export const resolveMemoryReview = (uid: string, resolution: string) =>
  apiFetch<{ ok: boolean; uid: string }>(`/api/v1/memory/state/review/${encodeURIComponent(uid)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });

export const memoryStateGraph = (uid: string, depth = 2) =>
  apiFetch<MemoryGraph>(
    `/api/v1/memory/state/graph/${encodeURIComponent(uid)}?depth=${encodeURIComponent(String(depth))}`,
  );

export const memoryStateStats = () =>
  apiFetch<MemoryStateStats>("/api/v1/memory/state/stats");

export const whatsappStatus = () =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/whatsapp/status");

export const whatsappCreate = () =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/whatsapp/create", {
    method: "POST",
    body: "{}",
  });

export const whatsappQrCode = () =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/whatsapp/qrcode");

export const whatsappPairingCode = (number: string) =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/whatsapp/pairing-code", {
    method: "POST",
    body: JSON.stringify({ number }),
  });

export const whatsappDisconnect = () =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/whatsapp/disconnect", {
    method: "POST",
    body: "{}",
  });

export const whatsappReset = () =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/whatsapp/reset", {
    method: "POST",
    body: "{}",
  });

export const telegramStatus = () =>
  apiFetch<Record<string, unknown>>("/api/v1/channels/telegram/status");

export const uploadMedia = (file: File, threadId?: string) => {
  const form = new FormData();
  form.append("file", file);
  if (threadId) form.append("thread_id", threadId);
  // Do NOT set Content-Type header — browser sets multipart boundary automatically.
  return apiFetch<{ attachment_id: string; url: string; mime_type: string; size_bytes: number }>(
    "/api/v1/media/upload",
    { method: "POST", body: form },
  );
};

export const repoStatus = () => apiFetch<RepoStatus>("/api/v1/repo/status");

export const repoLog = (limit = 50) =>
  apiFetch<RepoCommit[]>(`/api/v1/repo/log?limit=${limit}`);

export const repoBranches = () => apiFetch<RepoBranchSet>("/api/v1/repo/branches");

export const repoDiff = (mode: "working" | "staged", path?: string) => {
  const qs = new URLSearchParams({ mode });
  if (path) qs.set("path", path);
  return apiFetch<string>(`/api/v1/repo/diff?${qs.toString()}`);
};

export const setFeatureApproval = (
  featureId: string,
  payload: { decision: "approved" | "rejected"; note?: string },
) =>
  apiFetch<{ id: string; approval_status: string }>(`/api/v1/feature-requests/${featureId}/approval`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const triggerFeatureBuild = (featureId: string) =>
  apiFetch<{ run_id: string; trace_id: string; feature_id: string; status: string }>(
    `/api/v1/feature-requests/${featureId}/build`,
    { method: "POST", body: "{}" },
  );

export const listFeatureBuildRuns = (featureId: string, limit = 10) =>
  apiFetch<{ items: FeatureBuildRun[]; feature_id: string }>(
    `/api/v1/feature-requests/${featureId}/build-runs?limit=${limit}`,
  );

export const listApprovals = (params?: {
  action?: string;
  status?: string;
  target_ref?: string;
  limit?: number;
  offset?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.action) qs.set("action", params.action);
  if (params?.status) qs.set("status", params.status);
  if (params?.target_ref) qs.set("target_ref", params.target_ref);
  if (typeof params?.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params?.offset === "number") qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<{ items: ApprovalRecord[]; allowed_actions: string[] }>(`/api/v1/approvals${suffix}`);
};

export const createApproval = (payload: {
  action: string;
  target_ref?: string;
  ttl_minutes?: number;
}) =>
  apiFetch<{ approval_id: string; action: string; target_ref: string; ttl_minutes: number }>(
    "/api/v1/approvals",
    { method: "POST", body: JSON.stringify(payload) },
  );

export const revokeApproval = (approvalId: string) =>
  apiFetch<{ approval_id: string; status: string }>(`/api/v1/approvals/${approvalId}/revoke`, {
    method: "POST",
    body: "{}",
  });

export const repoCheckout = (payload: { branch?: string; create_branch?: string }) =>
  apiFetch<{ status: string }>("/api/v1/repo/checkout", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const repoStage = (payload: { paths?: string[]; all?: boolean }) =>
  apiFetch<{ status: string }>("/api/v1/repo/stage", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const repoUnstage = (paths: string[]) =>
  apiFetch<{ status: string }>("/api/v1/repo/unstage", {
    method: "POST",
    body: JSON.stringify(paths),
  });

export const repoCommit = (message: string) =>
  apiFetch<{ status: string }>("/api/v1/repo/commit", {
    method: "POST",
    body: JSON.stringify({ message }),
  });

export const repoPush = (set_upstream = false) =>
  apiFetch<{ status: string }>("/api/v1/repo/push", {
    method: "POST",
    body: JSON.stringify({ set_upstream }),
  });
