import { apiFetch } from "./client";
import type {
  AgentDetail,
  AgentSummary,
  BugReport,
  DispatchItem,
  EventItem,
  MemoryItem,
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
} from "../types";

export const login = (password: string) =>
  apiFetch<{ token: string; user_id: string }>("/api/v1/auth/login", {
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

export const memoryConsistencyReport = (limit = 50) =>
  apiFetch<Record<string, unknown>>(`/api/v1/memory/state/consistency/report?limit=${encodeURIComponent(String(limit))}`);

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
