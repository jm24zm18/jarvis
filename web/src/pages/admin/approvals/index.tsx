import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, Plus, X } from "lucide-react";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Input from "../../../components/ui/Input";
import { listApprovals, createApproval, revokeApproval } from "../../../api/endpoints";
import type { ApprovalRecord } from "../../../types";

// ── Create approval modal ─────────────────────────────────────────────────────
function CreateApprovalModal({
    allowedActions,
    onClose,
}: {
    allowedActions: string[];
    onClose: () => void;
}) {
    const qc = useQueryClient();
    const [action, setAction] = useState(allowedActions[0] ?? "selfupdate.apply");
    const [targetRef, setTargetRef] = useState("");
    const [ttlMinutes, setTtlMinutes] = useState(30);

    const createMutation = useMutation({
        mutationFn: () =>
            createApproval({ action, target_ref: targetRef, ttl_minutes: ttlMinutes }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["approvals"] });
            onClose();
        },
    });

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div className="bg-[var(--bg-primary)] border border-[var(--border-default)] rounded-xl p-6 w-full max-w-md space-y-4 shadow-xl">
                <h2 className="text-lg font-semibold text-[var(--text-primary)]">Create Approval Token</h2>
                <div className="space-y-1">
                    <label className="text-xs text-[var(--text-muted)]">Action</label>
                    <select
                        className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] p-2 text-sm"
                        value={action}
                        onChange={e => setAction(e.target.value)}
                    >
                        {allowedActions.map(a => (
                            <option key={a} value={a}>{a}</option>
                        ))}
                    </select>
                </div>
                <div className="space-y-1">
                    <label className="text-xs text-[var(--text-muted)]">Target Ref (e.g. trace_id, optional)</label>
                    <Input
                        placeholder="Leave blank for wildcard"
                        value={targetRef}
                        onChange={e => setTargetRef(e.target.value)}
                    />
                </div>
                <div className="space-y-1">
                    <label className="text-xs text-[var(--text-muted)]">TTL (minutes)</label>
                    <Input
                        type="number"
                        placeholder="30"
                        value={String(ttlMinutes)}
                        onChange={e => setTtlMinutes(Number(e.target.value))}
                    />
                </div>
                <div className="flex gap-2 justify-end">
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button
                        variant="primary"
                        onClick={() => createMutation.mutate()}
                        disabled={createMutation.isPending}
                    >
                        {createMutation.isPending ? "Creating…" : "Create"}
                    </Button>
                </div>
            </div>
        </div>
    );
}

// ── Approval row ──────────────────────────────────────────────────────────────
function ApprovalRow({ item }: { item: ApprovalRecord }) {
    const qc = useQueryClient();
    const revokeMutation = useMutation({
        mutationFn: () => revokeApproval(item.id),
        onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
    });

    const statusColor =
        item.status === "approved"
            ? "success"
            : item.status === "revoked"
            ? "danger"
            : "default";

    return (
        <div className="flex items-center justify-between gap-3 text-sm border-b border-[var(--border-default)] py-3 last:border-0">
            <div className="flex-1 min-w-0 space-y-0.5">
                <div className="font-medium text-[var(--text-primary)] truncate">{item.action}</div>
                {item.target_ref && (
                    <div className="text-xs text-[var(--text-muted)] font-mono truncate">
                        ref: {item.target_ref}
                    </div>
                )}
                <div className="text-xs text-[var(--text-muted)]">
                    by {item.actor_id} · {item.created_at.slice(0, 19)}
                    {item.expires_at && ` · expires ${item.expires_at.slice(0, 19)}`}
                </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
                <Badge variant={statusColor}>{item.status}</Badge>
                {item.status === "approved" && (
                    <button
                        onClick={() => revokeMutation.mutate()}
                        disabled={revokeMutation.isPending}
                        className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:opacity-80 disabled:opacity-50"
                    >
                        <X size={11} /> Revoke
                    </button>
                )}
            </div>
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AdminApprovalsPage() {
    const [showCreate, setShowCreate] = useState(false);
    const [actionFilter, setActionFilter] = useState("");
    const [statusFilter, setStatusFilter] = useState("");

    const { data, isLoading } = useQuery({
        queryKey: ["approvals", actionFilter, statusFilter],
        queryFn: () =>
            listApprovals({
                action: actionFilter || undefined,
                status: statusFilter || undefined,
                limit: 100,
            }),
    });

    const items: ApprovalRecord[] = data?.items ?? [];
    const allowedActions: string[] = data?.allowed_actions ?? [];

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <Header
                    title="Approvals Center"
                    subtitle="Manage active and historical approval tokens"
                    icon={<ShieldCheck className="h-6 w-6" />}
                />
                <Button
                    variant="primary"
                    icon={<Plus className="h-4 w-4" />}
                    onClick={() => setShowCreate(true)}
                >
                    Create Approval
                </Button>
            </div>

            {/* Filters */}
            <div className="flex gap-3 flex-wrap">
                <select
                    className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] px-3 py-2 text-sm"
                    value={actionFilter}
                    onChange={e => setActionFilter(e.target.value)}
                >
                    <option value="">All actions</option>
                    {allowedActions.map(a => (
                        <option key={a} value={a}>{a}</option>
                    ))}
                </select>
                <select
                    className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] px-3 py-2 text-sm"
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value)}
                >
                    <option value="">All statuses</option>
                    <option value="approved">Active</option>
                    <option value="consumed">Consumed</option>
                    <option value="revoked">Revoked</option>
                </select>
            </div>

            <Card>
                {isLoading && (
                    <p className="text-sm text-[var(--text-muted)] text-center py-6">Loading…</p>
                )}
                {!isLoading && items.length === 0 && (
                    <p className="text-sm text-[var(--text-muted)] text-center py-6">No approvals found</p>
                )}
                {items.map(item => (
                    <ApprovalRow key={item.id} item={item} />
                ))}
            </Card>

            {showCreate && (
                <CreateApprovalModal
                    allowedActions={allowedActions.length > 0 ? allowedActions : ["selfupdate.apply"]}
                    onClose={() => setShowCreate(false)}
                />
            )}
        </div>
    );
}
