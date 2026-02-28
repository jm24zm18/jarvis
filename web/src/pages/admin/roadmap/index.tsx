import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Map as MapIcon, Plus, Check, X, Play, ExternalLink } from "lucide-react";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Input from "../../../components/ui/Input";
import {
    listFeatureRequests,
    createFeatureRequest,
    setFeatureApproval,
    triggerFeatureBuild,
    listFeatureBuildRuns,
    listMessages,
} from "../../../api/endpoints";
import type { FeatureRequest, FeatureBuildRun, MessageItem } from "../../../types";

// ── Create modal ──────────────────────────────────────────────────────────────
function CreateFeatureModal({ onClose }: { onClose: () => void }) {
    const qc = useQueryClient();
    const [title, setTitle] = useState("");
    const [description, setDescription] = useState("");
    const [priority, setPriority] = useState("medium");

    const createMutation = useMutation({
        mutationFn: () => createFeatureRequest({ title, description, priority }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["roadmap-items"] });
            onClose();
        },
    });

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div className="bg-bg border border-[var(--color-border)] rounded-lg p-6 w-full max-w-md space-y-4 shadow-xl">
                <h2 className="text-lg font-mono text-xs font-semibold uppercase tracking-widest text-text2">New Feature Request</h2>
                <Input placeholder="Title" value={title} onChange={e => setTitle(e.target.value)} />
                <textarea
                    className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] text-text p-2 text-sm resize-none"
                    rows={4}
                    placeholder="Description"
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                />
                <select
                    className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] text-text p-2 text-sm"
                    value={priority}
                    onChange={e => setPriority(e.target.value)}
                >
                    {["low", "medium", "high", "critical"].map(p => (
                        <option key={p} value={p}>{p}</option>
                    ))}
                </select>
                <div className="flex gap-2 justify-end">
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button
                        variant="primary"
                        onClick={() => createMutation.mutate()}
                        disabled={!title.trim() || createMutation.isPending}
                    >
                        {createMutation.isPending ? "Creating…" : "Create"}
                    </Button>
                </div>
            </div>
        </div>
    );
}

// ── Approval modal ─────────────────────────────────────────────────────────
function ApprovalModal({
    feature,
    decision,
    onClose,
}: {
    feature: FeatureRequest;
    decision: "approved" | "rejected";
    onClose: () => void;
}) {
    const qc = useQueryClient();
    const [note, setNote] = useState("");

    const approveMutation = useMutation({
        mutationFn: () => setFeatureApproval(feature.id, { decision, note }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["roadmap-items"] });
            onClose();
        },
    });

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div className="bg-bg border border-[var(--color-border)] rounded-lg p-6 w-full max-w-md space-y-4 shadow-xl">
                <h2 className="text-lg font-mono text-xs font-semibold uppercase tracking-widest text-text2">
                    {decision === "approved" ? "Approve" : "Reject"} Feature Request
                </h2>
                <p className="text-sm text-text3">{feature.title}</p>
                <Input
                    placeholder="Note (optional)"
                    value={note}
                    onChange={e => setNote(e.target.value)}
                />
                <div className="flex gap-2 justify-end">
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button
                        variant={decision === "approved" ? "primary" : "danger"}
                        onClick={() => approveMutation.mutate()}
                        disabled={approveMutation.isPending}
                    >
                        {approveMutation.isPending ? "Saving…" : decision === "approved" ? "Approve" : "Reject"}
                    </Button>
                </div>
            </div>
        </div>
    );
}

// ── Build runs panel ──────────────────────────────────────────────────────────
function BuildRunsPanel({ feature, onClose }: { feature: FeatureRequest; onClose: () => void }) {
    const qc = useQueryClient();
    const [selectedRunId, setSelectedRunId] = useState("");
    const [olderMessages, setOlderMessages] = useState<MessageItem[]>([]);
    const [olderCursor, setOlderCursor] = useState<string | undefined>(undefined);
    const [isLoadingOlder, setIsLoadingOlder] = useState(false);
    const [chatError, setChatError] = useState("");
    const chatScrollRef = useRef<HTMLDivElement | null>(null);
    const stickToBottomRef = useRef(true);

    const { data, isLoading: runsLoading } = useQuery({
        queryKey: ["feature-build-runs", feature.id],
        queryFn: () => listFeatureBuildRuns(feature.id),
        refetchInterval: 2500,
    });

    const buildMutation = useMutation({
        mutationFn: () => triggerFeatureBuild(feature.id),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["feature-build-runs", feature.id] });
        },
    });

    const runs: FeatureBuildRun[] = data?.items ?? [];

    const statusBadge = (s: string) => {
        if (s === "succeeded") return <Badge variant="success">{s}</Badge>;
        if (s === "failed" || s === "timed_out") return <Badge variant="danger">{s}</Badge>;
        if (s === "running") return <Badge variant="info">running</Badge>;
        return <Badge variant="default">{s}</Badge>;
    };

    useEffect(() => {
        if (runs.length === 0) {
            setSelectedRunId("");
            return;
        }
        setSelectedRunId(previous =>
            runs.some(run => run.id === previous) ? previous : runs[0].id,
        );
    }, [runs]);

    const selectedRun = useMemo(
        () => runs.find(run => run.id === selectedRunId) ?? null,
        [runs, selectedRunId],
    );
    const selectedThreadId = selectedRun?.thread_id?.trim() ?? "";

    const messagesQuery = useQuery({
        queryKey: ["feature-build-run-messages", selectedRunId, selectedThreadId],
        queryFn: () => listMessages(selectedThreadId, undefined, 100),
        enabled: Boolean(selectedThreadId),
        refetchInterval: 2500,
        retry: 1,
    });

    useEffect(() => {
        setOlderMessages([]);
        setOlderCursor(undefined);
        setChatError("");
        stickToBottomRef.current = true;
    }, [selectedThreadId]);

    useEffect(() => {
        if (!messagesQuery.isError) {
            setChatError("");
        }
    }, [messagesQuery.isError]);

    useEffect(() => {
        if (messagesQuery.data && olderMessages.length === 0) {
            setOlderCursor(messagesQuery.data.next_before);
        }
    }, [messagesQuery.data, olderMessages.length]);

    const mergedMessages = useMemo(() => {
        const map = new Map<string, MessageItem>();
        for (const msg of [...olderMessages, ...(messagesQuery.data?.items ?? [])]) {
            map.set(msg.id, msg);
        }
        return Array.from(map.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
    }, [olderMessages, messagesQuery.data]);

    useEffect(() => {
        const viewport = chatScrollRef.current;
        if (!viewport || !stickToBottomRef.current) {
            return;
        }
        viewport.scrollTop = viewport.scrollHeight;
    }, [mergedMessages.length]);

    const onChatScroll = () => {
        const viewport = chatScrollRef.current;
        if (!viewport) {
            return;
        }
        const distanceToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
        stickToBottomRef.current = distanceToBottom < 72;
    };

    const loadOlder = async () => {
        if (!selectedThreadId || !olderCursor || isLoadingOlder) {
            return;
        }
        setIsLoadingOlder(true);
        setChatError("");
        try {
            const data = await listMessages(selectedThreadId, olderCursor, 100);
            setOlderMessages(existing => {
                const map = new Map<string, MessageItem>();
                for (const msg of [...data.items, ...existing]) {
                    map.set(msg.id, msg);
                }
                return Array.from(map.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
            });
            setOlderCursor(data.next_before);
        } catch (err) {
            const text = err instanceof Error ? err.message : "Failed to load older messages";
            setChatError(text);
        } finally {
            setIsLoadingOlder(false);
        }
    };

    const runMetaTimestamp = (value: string) => value ? value.slice(0, 19) : "n/a";

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div className="bg-bg border border-[var(--color-border)] rounded-lg p-6 w-full max-w-6xl h-[85vh] shadow-xl flex flex-col gap-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-mono text-xs font-semibold uppercase tracking-widest text-text2">Build Runs</h2>
                    <button onClick={onClose} className="text-text3 hover:text-text">
                        <X size={16} />
                    </button>
                </div>
                <p className="text-sm text-text3 truncate">{feature.title}</p>
                <Button
                    variant="primary"
                    icon={<Play className="h-4 w-4" />}
                    onClick={() => buildMutation.mutate()}
                    disabled={buildMutation.isPending}
                >
                    {buildMutation.isPending ? "Queuing…" : "Run Build"}
                </Button>
                {buildMutation.isSuccess && (
                    <p className="text-xs text-emerald-500">
                        Queued — trace: {buildMutation.data.trace_id}
                    </p>
                )}
                {buildMutation.isError && (
                    <p className="text-xs text-red-500">Failed to queue build</p>
                )}
                <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 flex-1 min-h-0">
                    <div className="border border-[var(--color-border)] rounded-lg overflow-hidden min-h-0 flex flex-col">
                        <div className="px-3 py-2 text-xs font-semibold text-text3 border-b border-[var(--color-border)]">
                            Runs
                        </div>
                        <div className="flex-1 overflow-y-auto p-2 space-y-2">
                            {runsLoading && runs.length === 0 && (
                                <p className="text-xs text-text3 text-center py-4">Loading runs…</p>
                            )}
                            {runs.length === 0 && !runsLoading && (
                                <p className="text-xs text-text3 text-center py-4">No build runs yet</p>
                            )}
                            {runs.map(run => (
                                <div
                                    key={run.id}
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setSelectedRunId(run.id)}
                                    onKeyDown={event => {
                                        if (event.key === "Enter" || event.key === " ") {
                                            event.preventDefault();
                                            setSelectedRunId(run.id);
                                        }
                                    }}
                                    className={`w-full text-left text-xs border rounded-lg p-2 transition cursor-pointer ${
                                        selectedRunId === run.id
                                            ? "border-accent bg-[var(--color-surface)]"
                                            : "border-[var(--color-border)] hover:bg-[var(--color-surface)]"
                                    }`}
                                >
                                    <div className="flex items-center justify-between gap-2">
                                        {statusBadge(run.status)}
                                        {run.trace_id && (
                                            <Link
                                                to={`/admin/events?trace_id=${encodeURIComponent(run.trace_id)}`}
                                                className="text-accent hover:underline flex items-center gap-1"
                                            >
                                                <ExternalLink size={12} /> Trace
                                            </Link>
                                        )}
                                    </div>
                                    <div className="text-text3 font-mono mt-1">
                                        {runMetaTimestamp(run.created_at)}
                                    </div>
                                    {run.summary && (
                                        <div className="text-text3 mt-1 line-clamp-2">{run.summary}</div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="border border-[var(--color-border)] rounded-lg overflow-hidden min-h-0 flex flex-col">
                        <div className="px-3 py-2 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
                            <div className="flex items-center justify-between gap-2">
                                <h3 className="text-sm font-semibold text-text">Build Chat</h3>
                                {selectedRun && (
                                    <div className="flex items-center gap-2">
                                        {selectedRun.trace_id && (
                                            <Link
                                                to={`/admin/events?trace_id=${encodeURIComponent(selectedRun.trace_id)}`}
                                                className="text-xs text-accent hover:underline"
                                            >
                                                Open full Events trace
                                            </Link>
                                        )}
                                        {selectedThreadId && (
                                            <Link
                                                to={`/chat/${selectedThreadId}`}
                                                className="text-xs text-accent hover:underline"
                                            >
                                                Open Chat thread
                                            </Link>
                                        )}
                                    </div>
                                )}
                            </div>
                            {selectedRun && (
                                <div className="mt-2 text-xs text-text3 flex flex-wrap gap-2 items-center">
                                    {statusBadge(selectedRun.status)}
                                    <span>trace: <span className="font-mono">{selectedRun.trace_id?.slice(0, 12) || "n/a"}</span></span>
                                    <span>created: <span className="font-mono">{runMetaTimestamp(selectedRun.created_at)}</span></span>
                                    <span>updated: <span className="font-mono">{runMetaTimestamp(selectedRun.updated_at)}</span></span>
                                </div>
                            )}
                        </div>

                        <div className="px-3 py-2 border-b border-[var(--color-border)]">
                            {selectedRun?.summary ? (
                                <p className="text-xs text-text3">{selectedRun.summary}</p>
                            ) : (
                                <p className="text-xs text-text3">Build progress stream.</p>
                            )}
                        </div>

                        <div ref={chatScrollRef} onScroll={onChatScroll} className="flex-1 overflow-y-auto p-3 space-y-3">
                            {!selectedRun && (
                                <div className="text-xs text-text3 text-center py-8">
                                    Select a build run to monitor live progress.
                                </div>
                            )}

                            {selectedRun && !selectedThreadId && (
                                <div className="text-xs text-text3 text-center py-8">
                                    No thread attached yet. This run is likely still queued.
                                </div>
                            )}

                            {selectedRun && selectedThreadId && olderCursor && (
                                <div className="flex justify-center">
                                    <Button variant="secondary" onClick={loadOlder} disabled={isLoadingOlder}>
                                        {isLoadingOlder ? "Loading older…" : "Load older"}
                                    </Button>
                                </div>
                            )}

                            {selectedRun && selectedThreadId && messagesQuery.isLoading && mergedMessages.length === 0 && (
                                <div className="text-xs text-text3 text-center py-8">Loading messages…</div>
                            )}

                            {selectedRun && selectedThreadId && (messagesQuery.isError || chatError) && (
                                <div className="border border-red-300 rounded-lg p-3 text-xs text-red-600 bg-red-50 dark:bg-red-900/20 dark:border-red-800">
                                    <p>Failed to fetch chat messages.</p>
                                    <div className="mt-2">
                                        <Button variant="secondary" onClick={() => messagesQuery.refetch()}>
                                            Retry
                                        </Button>
                                    </div>
                                </div>
                            )}

                            {selectedRun &&
                                selectedThreadId &&
                                !messagesQuery.isLoading &&
                                !messagesQuery.isError &&
                                mergedMessages.length === 0 && (
                                    <div className="text-xs text-text3 text-center py-8">
                                        Build has not produced messages yet.
                                    </div>
                                )}

                            {mergedMessages.map(msg => (
                                <div
                                    key={msg.id}
                                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                                >
                                    <div
                                        className={`max-w-[80%] rounded-lg px-3 py-2 text-xs ${
                                            msg.role === "user"
                                                ? "bg-blue-100 dark:bg-blue-900/30 text-blue-900 dark:text-blue-100"
                                                : "bg-[var(--color-surface)] border border-[var(--color-border)] text-text"
                                        }`}
                                    >
                                        <div className="font-semibold mb-1">
                                            {msg.speaker || (msg.role === "user" ? "User" : "Assistant")}
                                        </div>
                                        <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                                        <div className="mt-1 text-[10px] opacity-70 font-mono">
                                            {runMetaTimestamp(msg.created_at)}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── Feature card ──────────────────────────────────────────────────────────────
function FeatureCard({ item }: { item: FeatureRequest }) {
    const [approvalModal, setApprovalModal] = useState<"approved" | "rejected" | null>(null);
    const [showBuildRuns, setShowBuildRuns] = useState(false);

    const approvalColor =
        item.approval_status === "approved"
            ? "success"
            : item.approval_status === "rejected"
            ? "danger"
            : "default";

    return (
        <>
            <Card className="space-y-2">
                <div className="text-sm font-mono text-xs font-semibold uppercase tracking-widest text-text2">{item.title}</div>
                <div className="flex justify-between items-center text-xs flex-wrap gap-1">
                    <Badge variant={item.priority === "critical" || item.priority === "high" ? "danger" : "info"}>
                        {item.priority}
                    </Badge>
                    <Badge variant={approvalColor}>{item.approval_status}</Badge>
                    <span className="text-text3 font-mono">{item.id.slice(0, 8)}</span>
                </div>
                <div className="flex gap-1 flex-wrap">
                    {item.approval_status === "pending" && (
                        <>
                            <button
                                onClick={() => setApprovalModal("approved")}
                                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 hover:opacity-80"
                            >
                                <Check size={11} /> Approve
                            </button>
                            <button
                                onClick={() => setApprovalModal("rejected")}
                                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:opacity-80"
                            >
                                <X size={11} /> Reject
                            </button>
                        </>
                    )}
                    {item.approval_status === "approved" && (
                        <button
                            onClick={() => setShowBuildRuns(true)}
                            className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 hover:opacity-80"
                        >
                            <Play size={11} /> Build
                        </button>
                    )}
                </div>
            </Card>

            {approvalModal && (
                <ApprovalModal
                    feature={item}
                    decision={approvalModal}
                    onClose={() => setApprovalModal(null)}
                />
            )}
            {showBuildRuns && (
                <BuildRunsPanel feature={item} onClose={() => setShowBuildRuns(false)} />
            )}
        </>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AdminRoadmapPage() {
    const [search, setSearch] = useState("");
    const [approvalFilter, setApprovalFilter] = useState<string>("");
    const [statusFilter, setStatusFilter] = useState<string>("");
    const [showCreate, setShowCreate] = useState(false);

    const { data } = useQuery({
        queryKey: ["roadmap-items", approvalFilter, statusFilter],
        queryFn: () =>
            listFeatureRequests({
                approval_status: approvalFilter || undefined,
                status: statusFilter || undefined,
            }),
    });

    const columns = [
        { key: "open", label: "Open Backlog", bg: "bg-[var(--color-surface)]" },
        { key: "in_progress", label: "In Progress", bg: "bg-blue-50 dark:bg-blue-900/10" },
        { key: "resolved", label: "Resolved", bg: "bg-emerald-50 dark:bg-emerald-900/10" },
        { key: "closed", label: "Closed", bg: "bg-[var(--color-surface)]" },
    ];

    const items: FeatureRequest[] = (data?.items ?? []).filter(
        item =>
            search === "" ||
            item.title.toLowerCase().includes(search.toLowerCase()),
    );

    return (
        <div className="space-y-6 h-full flex flex-col min-h-screen">
            <div className="flex items-center justify-between">
                <Header
                    title="Feature Roadmap"
                    subtitle="Kanban board reflecting system feature requests"
                    icon={<MapIcon className="h-6 w-6" />}
                />
                <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setShowCreate(true)}>
                    New Feature Request
                </Button>
            </div>

            {/* Filters */}
            <div className="flex gap-3 flex-wrap">
                <div className="flex-1 min-w-[200px]">
                    <Input
                        placeholder="Search features…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                    />
                </div>
                <select
                    className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] text-text px-3 py-2 text-sm"
                    value={approvalFilter}
                    onChange={e => setApprovalFilter(e.target.value)}
                >
                    <option value="">All approvals</option>
                    <option value="pending">Pending</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                </select>
                <select
                    className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] text-text px-3 py-2 text-sm"
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value)}
                >
                    <option value="">All statuses</option>
                    <option value="open">Open</option>
                    <option value="in_progress">In Progress</option>
                    <option value="resolved">Resolved</option>
                    <option value="closed">Closed</option>
                </select>
            </div>

            {/* Kanban */}
            <div className="flex-1 flex gap-4 overflow-x-auto pb-4">
                {columns.map(col => {
                    const colItems = items.filter(item => item.status === col.key);
                    return (
                        <div
                            key={col.key}
                            className={`flex-1 min-w-[280px] rounded-lg flex flex-col border border-[var(--color-border)] ${col.bg}`}
                        >
                            <div className="p-3 border-b border-[var(--color-border)] flex justify-between items-center font-semibold text-sm">
                                <span>{col.label}</span>
                                <Badge variant="default">{colItems.length}</Badge>
                            </div>
                            <div className="p-3 flex-1 overflow-y-auto space-y-3">
                                {colItems.map(item => (
                                    <FeatureCard key={item.id} item={item} />
                                ))}
                                {colItems.length === 0 && (
                                    <div className="text-center p-4 text-xs text-text3 border-2 border-dashed border-[var(--color-border-2)] rounded-lg">
                                        No features {col.label.toLowerCase()}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {showCreate && <CreateFeatureModal onClose={() => setShowCreate(false)} />}
        </div>
    );
}
