import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Map, Plus, Check, X, Play, ExternalLink } from "lucide-react";
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
} from "../../../api/endpoints";
import type { FeatureRequest, FeatureBuildRun } from "../../../types";

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
            <div className="bg-[var(--bg-primary)] border border-[var(--border-default)] rounded-xl p-6 w-full max-w-md space-y-4 shadow-xl">
                <h2 className="text-lg font-semibold text-[var(--text-primary)]">New Feature Request</h2>
                <Input placeholder="Title" value={title} onChange={e => setTitle(e.target.value)} />
                <textarea
                    className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] p-2 text-sm resize-none"
                    rows={4}
                    placeholder="Description"
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                />
                <select
                    className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] p-2 text-sm"
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
            <div className="bg-[var(--bg-primary)] border border-[var(--border-default)] rounded-xl p-6 w-full max-w-md space-y-4 shadow-xl">
                <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                    {decision === "approved" ? "Approve" : "Reject"} Feature Request
                </h2>
                <p className="text-sm text-[var(--text-muted)]">{feature.title}</p>
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
    const { data } = useQuery({
        queryKey: ["feature-build-runs", feature.id],
        queryFn: () => listFeatureBuildRuns(feature.id),
    });

    const buildMutation = useMutation({
        mutationFn: () => triggerFeatureBuild(feature.id),
    });

    const runs: FeatureBuildRun[] = data?.items ?? [];

    const statusBadge = (s: string) => {
        if (s === "succeeded") return <Badge variant="success">{s}</Badge>;
        if (s === "failed" || s === "timed_out") return <Badge variant="danger">{s}</Badge>;
        if (s === "running") return <Badge variant="info">running</Badge>;
        return <Badge variant="default">{s}</Badge>;
    };

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div className="bg-[var(--bg-primary)] border border-[var(--border-default)] rounded-xl p-6 w-full max-w-lg space-y-4 shadow-xl">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-[var(--text-primary)]">Build Runs</h2>
                    <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                        <X size={16} />
                    </button>
                </div>
                <p className="text-sm text-[var(--text-muted)] truncate">{feature.title}</p>
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
                <div className="space-y-2 max-h-64 overflow-y-auto">
                    {runs.length === 0 && (
                        <p className="text-xs text-[var(--text-muted)] text-center py-4">No build runs yet</p>
                    )}
                    {runs.map(run => (
                        <div key={run.id} className="flex items-center justify-between text-xs border border-[var(--border-default)] rounded-lg p-2">
                            <div className="space-y-0.5">
                                {statusBadge(run.status)}
                                <div className="text-[var(--text-muted)] font-mono">{run.created_at.slice(0, 19)}</div>
                                {run.summary && <div className="text-[var(--text-muted)]">{run.summary}</div>}
                            </div>
                            {run.trace_id && (
                                <a
                                    href={`/admin/events?trace_id=${encodeURIComponent(run.trace_id)}`}
                                    className="text-[var(--color-brand)] hover:underline flex items-center gap-1"
                                >
                                    <ExternalLink size={12} /> Trace
                                </a>
                            )}
                        </div>
                    ))}
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
                <div className="text-sm font-semibold text-[var(--text-primary)]">{item.title}</div>
                <div className="flex justify-between items-center text-xs flex-wrap gap-1">
                    <Badge variant={item.priority === "critical" || item.priority === "high" ? "danger" : "info"}>
                        {item.priority}
                    </Badge>
                    <Badge variant={approvalColor}>{item.approval_status}</Badge>
                    <span className="text-[var(--text-muted)] font-mono">{item.id.slice(0, 8)}</span>
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
        { key: "open", label: "Open Backlog", bg: "bg-surface" },
        { key: "in_progress", label: "In Progress", bg: "bg-blue-50 dark:bg-blue-900/10" },
        { key: "resolved", label: "Resolved", bg: "bg-emerald-50 dark:bg-emerald-900/10" },
        { key: "closed", label: "Closed", bg: "bg-surface" },
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
                    icon={<Map className="h-6 w-6" />}
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
                    className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] px-3 py-2 text-sm"
                    value={approvalFilter}
                    onChange={e => setApprovalFilter(e.target.value)}
                >
                    <option value="">All approvals</option>
                    <option value="pending">Pending</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                </select>
                <select
                    className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] px-3 py-2 text-sm"
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
                            className={`flex-1 min-w-[280px] rounded-xl flex flex-col border border-[var(--border-default)] ${col.bg}`}
                        >
                            <div className="p-3 border-b border-[var(--border-default)] flex justify-between items-center font-semibold text-sm">
                                <span>{col.label}</span>
                                <Badge variant="default">{colItems.length}</Badge>
                            </div>
                            <div className="p-3 flex-1 overflow-y-auto space-y-3">
                                {colItems.map(item => (
                                    <FeatureCard key={item.id} item={item} />
                                ))}
                                {colItems.length === 0 && (
                                    <div className="text-center p-4 text-xs text-[var(--text-muted)] border-2 border-dashed border-[var(--border-strong)] rounded-lg">
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
