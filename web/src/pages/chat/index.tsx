import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { Send, Search, Plus, Eye, EyeOff, Paperclip, Mic } from "lucide-react";
import {
  createThread,
  getTrace,
  getOnboardingStatus,
  listEvents,
  listMessages,
  listThreads,
  sendMessage,
  startOnboarding,
  uploadMedia,
} from "../../api/endpoints";
import type { MediaAttachment, MessageItem, OnboardingStatus } from "../../types";
import { useWebSocket } from "../../hooks/useWebSocket";
import { useChatStore } from "../../stores/chat";
import { useAuthStore } from "../../stores/auth";
import Button from "../../components/ui/Button";
import MarkdownLite from "../../components/ui/MarkdownLite";
import ThinkingPanel from "../../components/ui/ThinkingPanel";
import { sanitizeForInlinePreview } from "../../components/ui/textSanitizer";

const EMPTY_TRACE_EVENTS: Array<{ event_type: string; payload: Record<string, unknown>; created_at: string }> = [];

const COMMANDS: Array<{ value: string; help: string }> = [
  { value: "/status", help: "Show provider, queue, and scheduler health." },
  { value: "/verbose on", help: "Enable verbose mode for this thread." },
  { value: "/verbose off", help: "Disable verbose mode for this thread." },
  { value: "/group on researcher", help: "Enable an agent for this thread." },
  { value: "/group off researcher", help: "Disable an agent for this thread." },
  { value: "/compact", help: "Queue memory compaction for this thread." },
  { value: "/logs trace <trace_id>", help: "Show events for a trace id." },
  { value: "/logs search <query>", help: "Search event logs for matching text." },
  { value: "/kb list", help: "List saved knowledge base docs." },
  { value: "/kb search <query>", help: "Search knowledge base docs." },
  { value: "/kb get <id-or-title>", help: "Read a knowledge base document." },
  { value: "/kb add <title> :: <content>", help: "Save text into the knowledge base." },
  { value: "/channel-approve-list", help: "List pending non-web reply approvals." },
  { value: "/channel-approve <id> once", help: "Approve one pending non-web reply." },
  { value: "/channel-approve <id> always", help: "Approve and always allow sender+channel." },
  { value: "/channel-deny <id> [reason]", help: "Reject a pending non-web reply." },
  { value: "/channel-allow-list", help: "List active sender+channel allow rules." },
  { value: "/channel-allow-revoke <channel> <recipient>", help: "Revoke allow rule." },
  { value: "/onboarding reset", help: "Force onboarding flow to run again." },
  { value: "/new", help: "Close this thread and create a new one." },
];

function toThreadPreview(content?: string | null): string {
  if (!content) return "No messages yet";
  let text = sanitizeForInlinePreview(content);
  text = text.replace(/```[\s\S]*?```/g, " [code] ");
  text = text.replace(/`([^`]+)`/g, "$1");
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, "$1");
  text = text.replace(/\*\*([^*]+)\*\*/g, "$1");
  text = text.replace(/\*([^*]+)\*/g, "$1");
  text = text.replace(/(^|\s)#{1,6}\s+/g, "$1");
  text = text.replace(/(^|\s)-\s+/g, "$1");
  text = text.replace(/(^|\s)\d+\.\s+/g, "$1");
  text = text.replace(/\s+/g, " ").trim();
  return text || "No messages yet";
}

function toThreadName(thread: { id: string; last_message?: string | null }): string {
  const shortId = thread.id.startsWith("thr_") ? thread.id.slice(4, 12) : thread.id.slice(0, 8);
  const preview = toThreadPreview(thread.last_message);
  if (preview === "No messages yet") return `Thread ${shortId}`;
  const sentence = preview.split(/[.!?]/)[0]?.trim() ?? "";
  const compact = sentence.replace(/\s+/g, " ");
  if (!compact) return `Thread ${shortId}`;
  const max = 40;
  const label = compact.length > max ? `${compact.slice(0, max - 1).trimEnd()}…` : compact;
  return label;
}

function agentInitial(speaker: string): string {
  return (speaker[0] ?? "A").toUpperCase();
}

const agentColors = [
  "bg-violet-500", "bg-blue-500", "bg-emerald-500", "bg-amber-500", "bg-rose-500",
];

function agentColor(speaker: string): string {
  let hash = 0;
  for (let i = 0; i < speaker.length; i++) hash = (hash * 31 + speaker.charCodeAt(i)) | 0;
  return agentColors[Math.abs(hash) % agentColors.length];
}

export default function ChatPage() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [showThinking, setShowThinking] = useState(false);
  const [panelTraceId, setPanelTraceId] = useState("");
  const [threadFilter, setThreadFilter] = useState("");
  const panelTraceIdRef = useRef(panelTraceId);
  panelTraceIdRef.current = panelTraceId;
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const setThinking = useChatStore((s) => s.setThinking);
  const setDelegation = useChatStore((s) => s.setDelegation);
  const setActiveTrace = useChatStore((s) => s.setActiveTrace);
  const setTraceEvents = useChatStore((s) => s.setTraceEvents);
  const appendTraceEvent = useChatStore((s) => s.appendTraceEvent);
  const clearTrace = useChatStore((s) => s.clearTrace);
  const thinking = useChatStore((s) => (threadId ? !!s.thinkingByThread[threadId] : false));
  const delegation = useChatStore((s) => (threadId ? s.delegationByThread[threadId] : ""));
  const activeTraceId = useChatStore((s) => (threadId ? s.activeTraceByThread[threadId] : ""));
  const traceEventsByTrace = useChatStore((s) => s.traceEvents);
  const traceEvents = useMemo(
    () => (panelTraceId ? traceEventsByTrace[panelTraceId] ?? EMPTY_TRACE_EVENTS : EMPTY_TRACE_EVENTS),
    [panelTraceId, traceEventsByTrace],
  );
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "admin";
  const listRef = useRef<HTMLDivElement | null>(null);

  const threads = useQuery({
    queryKey: ["threads", isAdmin],
    queryFn: () => listThreads(isAdmin),
  });
  const messages = useQuery({
    queryKey: ["messages", threadId],
    queryFn: () => (threadId ? listMessages(threadId) : Promise.resolve({ items: [] })),
    enabled: !!threadId,
    refetchInterval: 10000,
  });
  const onboarding = useQuery({
    queryKey: ["onboarding", threadId],
    queryFn: () =>
      threadId
        ? getOnboardingStatus(threadId)
        : Promise.resolve<OnboardingStatus>({
          status: "not_required",
          required: false,
          question: null,
        }),
    enabled: !!threadId,
    refetchInterval: (query) => {
      const data = query.state.data as OnboardingStatus | undefined;
      if (!data) return 10000;
      return data.status === "required" || data.status === "in_progress" ? 10000 : false;
    },
  });

  const createThreadMutation = useMutation({
    mutationFn: createThread,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
      navigate(`/chat/${data.id}`);
    },
  });

  const startOnboardingMutation = useMutation({
    mutationFn: () => {
      if (!threadId) throw new Error("No thread selected");
      return startOnboarding(threadId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
      queryClient.invalidateQueries({ queryKey: ["onboarding", threadId] });
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });

  const sendMutation = useMutation({
    mutationFn: (content: string) => {
      if (!threadId) throw new Error("No thread selected");
      return sendMessage(threadId, content);
    },
    onMutate: async (content: string) => {
      if (!threadId) return { previous: undefined };
      clearTrace(threadId);
      setPanelTraceId("");
      const key = ["messages", threadId] as const;
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<{ items: MessageItem[] }>(key);
      const priorItems = previous?.items ?? [];
      const knownUserSpeaker =
        [...priorItems]
          .reverse()
          .find((item) => item.role === "user" && typeof item.speaker === "string")?.speaker ??
        "You";
      queryClient.setQueryData(key, {
        items: [
          ...priorItems,
          {
            id: `tmp_${Date.now()}`,
            role: "user",
            content,
            created_at: new Date().toISOString(),
            speaker: knownUserSpeaker,
          },
        ],
      });
      setDraft("");
      return { previous };
    },
    onError: (_err, _content, context) => {
      if (!threadId) return;
      if (context?.previous) {
        queryClient.setQueryData(["messages", threadId], context.previous);
      }
    },
    onSuccess: (data) => {
      if (data.trace_id && threadId) {
        setActiveTrace(threadId, data.trace_id);
        setPanelTraceId(data.trace_id);
      }
      queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
      queryClient.invalidateQueries({ queryKey: ["onboarding", threadId] });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
    },
  });

  const handleEvent = useCallback(
    (event: Record<string, unknown>) => {
      const type = String(event.type ?? "");
      const eventThreadId = String(event.thread_id ?? "");
      if (type === "message.new" && threadId && eventThreadId === threadId) {
        queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
        queryClient.invalidateQueries({ queryKey: ["threads"] });
      }
      if (type === "agent.thinking" && eventThreadId) setThinking(eventThreadId, true);
      if (type === "agent.done" && eventThreadId) {
        setThinking(eventThreadId, false);
        clearTrace(eventThreadId);
      }
      if (type === "agent.delegated" && eventThreadId) {
        const from = String(event.from_agent ?? "main");
        const to = String(event.to_agent ?? "worker");
        setDelegation(eventThreadId, `${from} -> ${to}`);
        const traceId = String(event.trace_id ?? "");
        if (traceId) {
          if (!panelTraceIdRef.current) setPanelTraceId(traceId);
          appendTraceEvent(traceId, {
            event_type: "agent.delegated",
            payload: event,
            created_at: String(event.created_at ?? new Date().toISOString()),
          });
        }
      }
      if (type.startsWith("trace.")) {
        const traceId = String(event.trace_id ?? "");
        if (traceId) {
          if (!panelTraceIdRef.current) setPanelTraceId(traceId);
          appendTraceEvent(traceId, {
            event_type: type.replace("trace.", ""),
            payload: event,
            created_at: String(event.created_at ?? new Date().toISOString()),
          });
        }
      }
    },
    [appendTraceEvent, clearTrace, queryClient, setDelegation, setThinking, threadId],
  );

  const ws = useWebSocket(handleEvent);

  useEffect(() => {
    if (!threadId) return;
    ws.subscribe(threadId);
    return () => ws.unsubscribe(threadId);
  }, [threadId, ws]);

  useEffect(() => {
    if (!threadId) {
      setPanelTraceId("");
      return;
    }
    const traceId = useChatStore.getState().activeTraceByThread[threadId] ?? "";
    setPanelTraceId(traceId);
  }, [threadId]);

  useEffect(() => {
    if (!threadId || panelTraceId) return;
    let cancelled = false;
    void listEvents({ thread_id: threadId, event_type: "agent.step.end" })
      .then((resp) => {
        if (cancelled) return;
        const latest = resp.items?.[0];
        const traceId = String(latest?.trace_id ?? "").trim();
        if (!traceId) return;
        setActiveTrace(threadId, traceId);
        setPanelTraceId(traceId);
      })
      .catch(() => {
        if (cancelled) return;
      });
    return () => {
      cancelled = true;
    };
  }, [panelTraceId, setActiveTrace, threadId]);

  useEffect(() => {
    if (!panelTraceId) return;
    let cancelled = false;
    const current = traceEventsByTrace[panelTraceId] ?? EMPTY_TRACE_EVENTS;
    if (current.length > 0) return;
    void getTrace(panelTraceId, "redacted")
      .then((data) => {
        if (cancelled) return;
        const hydrated = (data.items ?? []).map((item) => {
          let parsedFallback: Record<string, unknown> = {};
          if (item.payload_redacted_json) {
            try {
              const parsed = JSON.parse(item.payload_redacted_json);
              if (typeof parsed === "object" && parsed !== null) {
                parsedFallback = parsed as Record<string, unknown>;
              }
            } catch {
              parsedFallback = { raw: item.payload_redacted_json };
            }
          }
          return {
            event_type: item.event_type,
            payload: item.payload ?? parsedFallback,
            created_at: item.created_at,
          };
        });
        setTraceEvents(panelTraceId, hydrated);
      })
      .catch(() => {
        if (cancelled) return;
        setTraceEvents(panelTraceId, []);
      });
    return () => {
      cancelled = true;
    };
  }, [panelTraceId, setTraceEvents, traceEventsByTrace]);

  const threadItems = useMemo(() => threads.data?.items ?? [], [threads.data]);
  const filteredThreads = useMemo(() => {
    if (!threadFilter.trim()) return threadItems;
    const q = threadFilter.toLowerCase();
    return threadItems.filter(
      (t) =>
        t.id.toLowerCase().includes(q) ||
        toThreadName(t).toLowerCase().includes(q) ||
        toThreadPreview(t.last_message).toLowerCase().includes(q),
    );
  }, [threadItems, threadFilter]);
  const selectedThread = useMemo(
    () => threadItems.find((thread) => thread.id === threadId),
    [threadItems, threadId],
  );
  const messageItems = useMemo(() => messages.data?.items ?? [], [messages.data]);
  const onboardingBanner = useMemo(() => {
    const status = onboarding.data;
    if (!status) return "";
    if (status.status === "required") return "Onboarding required.";
    if (status.status === "in_progress") return "Onboarding in progress.";
    return "";
  }, [onboarding.data]);

  const hasOnboardingPrompt = useMemo(() => {
    const question = onboarding.data?.question?.trim();
    if (!question) return false;
    return messageItems.some(
      (msg) => msg.role === "assistant" && msg.content.trim() === question,
    );
  }, [messageItems, onboarding.data?.question]);

  useEffect(() => {
    if (!threadId) return;
    const status = onboarding.data;
    if (!status) return;
    if (status.status !== "required" && status.status !== "in_progress") return;
    if (!status.question?.trim()) return;
    if (hasOnboardingPrompt) return;
    if (startOnboardingMutation.isPending) return;
    startOnboardingMutation.mutate();
  }, [hasOnboardingPrompt, onboarding.data, startOnboardingMutation, threadId]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [threadId, messageItems.length, thinking]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [draft]);

  const trimmedDraft = draft.trimStart();
  const commandPrefix = trimmedDraft.split(/\s+/)[0]?.toLowerCase() ?? "";
  const showCommandSuggestions = !!threadId && trimmedDraft.startsWith("/");
  const commandSuggestions = useMemo(() => {
    if (!showCommandSuggestions) return [];
    if (!commandPrefix || commandPrefix === "/") return COMMANDS;
    return COMMANDS.filter((cmd) => cmd.value.toLowerCase().startsWith(commandPrefix));
  }, [commandPrefix, showCommandSuggestions]);
  const isTyping = thinking || sendMutation.isPending || startOnboardingMutation.isPending;
  const typingAgentName = useMemo(() => {
    const latestAssistantSpeaker = [...messageItems]
      .reverse()
      .find((msg) => msg.role === "assistant" && (msg.speaker ?? "").trim().length > 0)?.speaker;
    return latestAssistantSpeaker?.trim() || "Agent";
  }, [messageItems]);

  // Group consecutive messages from same speaker
  const groupedMessages = useMemo(() => {
    const groups: Array<{ speaker: string; role: string; messages: MessageItem[] }> = [];
    for (const msg of messageItems) {
      const speaker = msg.speaker ?? msg.role;
      const last = groups[groups.length - 1];
      if (last && last.speaker === speaker && last.role === msg.role) {
        last.messages.push(msg);
      } else {
        groups.push({ speaker, role: msg.role, messages: [msg] });
      }
    }
    return groups;
  }, [messageItems]);

  const handleMicPointerDown = useCallback(async () => {
    if (!threadId) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      // Mic permission denied or API unsupported — silent failure
    }
  }, [threadId]);

  const handleMicPointerUp = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state !== "recording") {
      setIsRecording(false);
      return;
    }
    setIsRecording(false);
    const stopped = new Promise<void>((resolve) => { recorder.onstop = () => resolve(); });
    recorder.stop();
    recorder.stream.getTracks().forEach((t) => t.stop());
    await stopped;
    const chunks = audioChunksRef.current;
    if (!chunks.length || !threadId) return;
    const blob = new Blob(chunks, { type: "audio/webm" });
    const file = new File([blob], `voice_${Date.now()}.webm`, { type: "audio/webm" });
    setIsUploading(true);
    try {
      await uploadMedia(file, threadId);
    } catch {
      // Non-fatal
    } finally {
      setIsUploading(false);
    }
    sendMutation.mutate("[voice message]");
  }, [sendMutation, threadId]);

  const handleSend = useCallback(async () => {
    if (!threadId) return;
    const content = draft.trim();
    const fileToUpload = pendingFile;
    if (!content && !fileToUpload) return;
    if (fileToUpload) {
      setIsUploading(true);
      setPendingFile(null);
      try {
        await uploadMedia(fileToUpload, threadId);
      } catch {
        // Non-fatal — upload failure doesn't block text send
      } finally {
        setIsUploading(false);
      }
      if (!content) {
        sendMutation.mutate("[media uploaded]");
        return;
      }
    }
    if (content) sendMutation.mutate(content);
  }, [draft, pendingFile, sendMutation, threadId]);

  return (
    <div className="flex h-[calc(100vh-3rem)] gap-4">
      {/* Thread sidebar */}
      <section className="flex w-72 shrink-0 flex-col rounded-xl border border-[var(--border-default)] bg-surface">
        <div className="border-b border-[var(--border-default)] p-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                value={threadFilter}
                onChange={(e) => setThreadFilter(e.target.value)}
                placeholder="Search threads..."
                className="w-full rounded-lg border border-[var(--border-strong)] bg-surface py-1.5 pl-8 pr-2 text-xs text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:border-ember"
              />
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={() => createThreadMutation.mutate()}
                className="rounded-lg bg-[#13293d] p-1.5 text-white hover:bg-[#13293d]/90 dark:bg-slate-200 dark:text-slate-900"
              >
                <Plus size={16} />
              </button>
            </div>
          </div>
        </div>
        <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {filteredThreads.map((thread) => (
            <button
              key={thread.id}
              className={`w-full rounded-lg p-2.5 text-left transition ${threadId === thread.id
                  ? "border-l-2 border-l-ember bg-mist"
                  : "hover:bg-mist/60"
                }`}
              onClick={() => navigate(`/chat/${thread.id}`)}
            >
              <div className="text-sm font-medium text-[var(--text-primary)] truncate">
                {toThreadName(thread)}
              </div>
              <div
                className="mt-0.5 overflow-hidden text-[11px] text-[var(--text-muted)]"
                style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}
              >
                {toThreadPreview(thread.last_message)}
              </div>
              <div className="mt-0.5 text-[10px] text-[var(--text-muted)]">
                {thread.updated_at ? new Date(thread.updated_at).toLocaleDateString() : ""}
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* Chat area */}
      <section className="flex min-w-0 flex-1 flex-col rounded-xl border border-[var(--border-default)] bg-surface">
        {/* Chat header */}
        <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
          <div>
            <h2 className="font-display text-lg text-[var(--text-primary)]">
              {selectedThread ? toThreadName(selectedThread) : "Select a thread"}
            </h2>
            {threadId && (
              <p className="text-[11px] text-[var(--text-muted)]">{threadId}</p>
            )}
          </div>
          {(isTyping || traceEvents.length > 0 || activeTraceId || panelTraceId) && (
            <Button
              variant="ghost"
              size="sm"
              icon={showThinking ? <EyeOff size={14} /> : <Eye size={14} />}
              onClick={() => setShowThinking((v) => !v)}
            >
              {showThinking ? "Hide" : "Think"}
            </Button>
          )}
        </div>

        {onboardingBanner ? (
          <div className="mx-4 mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-600 dark:bg-amber-900/30 dark:text-amber-300">
            {onboardingBanner}
          </div>
        ) : null}

        {/* Messages + thinking panel */}
        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 flex-1 flex-col">
            <div ref={listRef} className="min-h-0 flex-1 space-y-1 overflow-y-auto p-4">
              {groupedMessages.map((group, gIdx) => (
                <div key={gIdx} className={`flex min-w-0 gap-2.5 ${group.role === "user" ? "justify-end" : ""}`}>
                  {group.role !== "user" && (
                    <div className={`mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${agentColor(group.speaker)}`}>
                      {agentInitial(group.speaker)}
                    </div>
                  )}
                  <div className={`min-w-0 max-w-[85%] space-y-1 ${group.role === "user" ? "items-end" : ""}`}>
                    <div className="mb-0.5 text-[11px] font-medium text-[var(--text-muted)]">
                      {group.speaker}
                    </div>
                    {group.messages.map((msg) => (
                      <div
                        key={msg.id}
                        className={`group relative rounded-2xl px-3.5 py-2.5 text-sm shadow-sm ${msg.role === "user"
                            ? "bg-[#13293d] text-white dark:bg-slate-200 dark:text-slate-900"
                            : "bg-mist text-[var(--text-primary)]"
                          }`}
                        style={{ maxWidth: "78ch" }}
                      >
                        <div className="min-w-0 max-h-[32rem] overflow-x-auto break-words [overflow-wrap:anywhere]">
                          <MarkdownLite content={msg.content} />
                        </div>
                        {msg.media && msg.media.length > 0 && (
                          <div className="mt-1.5 space-y-1.5">
                            {(msg.media as MediaAttachment[]).map((att) => (
                              <div key={att.id}>
                                {att.mime_type.startsWith("image/") ? (
                                  <img
                                    src={att.thumbnail_url ?? att.url}
                                    alt="attachment"
                                    className="max-h-48 max-w-full rounded-lg object-cover cursor-pointer"
                                    onClick={() => window.open(att.url, "_blank")}
                                  />
                                ) : att.mime_type.startsWith("audio/") ? (
                                  <audio controls src={att.url} className="max-w-full" />
                                ) : (
                                  <a
                                    href={att.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1.5 rounded-lg border border-[var(--border-default)] px-2 py-1.5 text-xs hover:bg-mist transition"
                                  >
                                    <Paperclip size={12} />
                                    <span className="truncate">{att.mime_type}</span>
                                    <span className="ml-auto text-[var(--text-muted)]">{Math.round(att.size_bytes / 1024)}KB</span>
                                  </a>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                        <div className="absolute -bottom-4 right-2 hidden text-[10px] text-[var(--text-muted)] group-hover:block">
                          {new Date(msg.created_at).toLocaleTimeString()}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {isTyping ? (
                <div className="flex items-center gap-2.5">
                  <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${agentColor(typingAgentName)}`}>
                    {agentInitial(typingAgentName)}
                  </div>
                  <div className="rounded-2xl bg-mist px-4 py-3 shadow-sm">
                    <div className="mb-1 text-[11px] font-medium text-[var(--text-muted)]">
                      {typingAgentName}{delegation ? ` (${delegation})` : ""}
                    </div>
                    <div className="flex gap-1">
                      <span className="typing-dot h-2 w-2 rounded-full bg-[var(--text-muted)]" />
                      <span className="typing-dot h-2 w-2 rounded-full bg-[var(--text-muted)]" />
                      <span className="typing-dot h-2 w-2 rounded-full bg-[var(--text-muted)]" />
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
          {showThinking && (
            <ThinkingPanel events={traceEvents} onClose={() => setShowThinking(false)} />
          )}
        </div>

        {/* Command suggestions */}
        {showCommandSuggestions && commandSuggestions.length ? (
          <div className="mx-4 max-h-40 overflow-y-auto rounded-lg border border-[var(--border-default)] bg-surface p-1 shadow-lg">
            {commandSuggestions.map((cmd) => (
              <button
                key={cmd.value}
                type="button"
                className="w-full rounded-md px-2.5 py-1.5 text-left text-xs hover:bg-mist transition"
                onClick={() => setDraft(`${cmd.value} `)}
              >
                <div className="font-mono text-[11px] text-[var(--text-primary)]">{cmd.value}</div>
                <div className="text-[11px] text-[var(--text-muted)]">{cmd.help}</div>
              </button>
            ))}
          </div>
        ) : null}

        {/* Input area */}
        <div className="border-t border-[var(--border-default)] p-3">
          {/* Pending file preview */}
          {pendingFile && (
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-[var(--border-default)] bg-mist px-2.5 py-1.5 text-xs">
              <Paperclip size={12} className="text-[var(--text-muted)]" />
              <span className="flex-1 truncate text-[var(--text-primary)]">{pendingFile.name}</span>
              <span className="text-[var(--text-muted)]">{Math.round(pendingFile.size / 1024)}KB</span>
              <button
                type="button"
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                onClick={() => setPendingFile(null)}
              >
                ✕
              </button>
            </div>
          )}
          <div className="flex items-end gap-2">
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept="image/*,audio/*,video/*,application/pdf,text/plain"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setPendingFile(f);
                e.target.value = "";
              }}
            />
            {/* Paperclip button */}
            <button
              type="button"
              title="Attach file"
              disabled={!threadId || isUploading}
              onClick={() => fileInputRef.current?.click()}
              className="flex h-[2.5rem] w-[2.5rem] shrink-0 items-center justify-center rounded-xl border border-[var(--border-strong)] bg-surface text-[var(--text-muted)] transition hover:text-[var(--text-primary)] disabled:opacity-40"
            >
              <Paperclip size={16} />
            </button>
            <textarea
              ref={textareaRef}
              value={draft}
              placeholder={threadId ? "Type a message... (Shift+Enter for newline)" : "Create/select a thread first"}
              onChange={(e) => setDraft(e.target.value)}
              disabled={!threadId || sendMutation.isPending || isUploading}
              rows={1}
              onKeyDown={(e) => {
                if (e.key === "Tab" && showCommandSuggestions && commandSuggestions.length > 0) {
                  e.preventDefault();
                  setDraft(`${commandSuggestions[0].value} `);
                  return;
                }
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              className="max-h-40 min-h-[2.5rem] flex-1 resize-none rounded-xl border border-[var(--border-strong)] bg-surface px-3.5 py-2.5 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:border-ember focus:ring-1 focus:ring-ember/30"
            />
            {/* Mic button — hold to record */}
            <button
              type="button"
              title="Hold to record voice"
              disabled={!threadId || isUploading || sendMutation.isPending}
              onPointerDown={() => { void handleMicPointerDown(); }}
              onPointerUp={() => { void handleMicPointerUp(); }}
              onPointerLeave={() => { void handleMicPointerUp(); }}
              className={`flex h-[2.5rem] w-[2.5rem] shrink-0 items-center justify-center rounded-xl border transition disabled:opacity-40 ${
                isRecording
                  ? "border-ember bg-ember text-white"
                  : "border-[var(--border-strong)] bg-surface text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              }`}
            >
              <Mic size={16} />
            </button>
            <Button
              onClick={() => { void handleSend(); }}
              disabled={!threadId || (!draft.trim() && !pendingFile) || sendMutation.isPending || isTyping || isUploading}
              icon={<Send size={16} />}
            >
              {isUploading ? "…" : "Send"}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
