import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bug, Plus, X, ArrowRight } from "lucide-react";
import { createBug, deleteBug, listBugs, updateBug } from "../../api/endpoints";
import type { BugReport } from "../../types";
import Header from "../../components/layout/Header";
import Button from "../../components/ui/Button";
import Input from "../../components/ui/Input";
import Badge from "../../components/ui/Badge";
import Card from "../../components/ui/Card";

const STATUS_OPTIONS = ["open", "in_progress", "resolved", "closed"] as const;
const PRIORITY_OPTIONS = ["low", "medium", "high", "critical"] as const;

const statusBadge: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
  open: "info",
  in_progress: "warning",
  resolved: "success",
  closed: "default",
};

const priorityBadge: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
  low: "default",
  medium: "info",
  high: "warning",
  critical: "danger",
};

const nextStatus: Record<string, string> = {
  open: "in_progress",
  in_progress: "resolved",
  resolved: "closed",
};

const selectCls =
  "rounded-md border border-[var(--color-border-2)] bg-[var(--color-surface-2)] px-2 py-1.5 font-mono text-sm text-text outline-none focus:border-accent";

export default function AdminBugsPage() {
  const queryClient = useQueryClient();
  const [filterStatus, setFilterStatus] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [filterSearch, setFilterSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState("");

  // Create form state
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newPriority, setNewPriority] = useState<string>("medium");
  const [newThreadId, setNewThreadId] = useState("");
  const [newTraceId, setNewTraceId] = useState("");

  const filters = useMemo(
    () => ({ status: filterStatus, priority: filterPriority, search: filterSearch }),
    [filterStatus, filterPriority, filterSearch],
  );

  const bugs = useQuery({
    queryKey: ["bugs", filters],
    queryFn: () => listBugs(filters),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createBug({
        title: newTitle,
        description: newDesc,
        priority: newPriority,
        thread_id: newThreadId || undefined,
        trace_id: newTraceId || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bugs"] });
      setShowCreate(false);
      setNewTitle("");
      setNewDesc("");
      setNewPriority("medium");
      setNewThreadId("");
      setNewTraceId("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) =>
      updateBug(id, payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["bugs"] }),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteBug(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bugs"] });
      setSelectedId("");
    },
  });

  const items: BugReport[] = bugs.data?.items ?? [];
  const selected = items.find((b) => b.id === selectedId);

  return (
    <div>
      <Header title="Bug Tracker" subtitle="Track and manage bug reports" icon={<Bug size={20} />} />

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="mb-1 block font-mono text-[10px] font-medium text-text3">Status</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className={selectCls}
          >
            <option value="">All</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{s.replace("_", " ")}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block font-mono text-[10px] font-medium text-text3">Priority</label>
          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value)}
            className={selectCls}
          >
            <option value="">All</option>
            {PRIORITY_OPTIONS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <Input
          value={filterSearch}
          onChange={(e) => setFilterSearch(e.target.value)}
          placeholder="Search bugs..."
          className="!w-48"
        />
        <Button onClick={() => void bugs.refetch()} variant="secondary" size="sm">
          Search
        </Button>
        <div className="flex-1" />
        <Button onClick={() => setShowCreate(true)} icon={<Plus size={16} />}>
          New Bug
        </Button>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card className="mb-4" header={
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Report a Bug</span>
            <button onClick={() => setShowCreate(false)} className="text-text3 hover:text-text">
              <X size={16} />
            </button>
          </div>
        }>
          <div className="space-y-3">
            <Input label="Title" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="Bug title" />
            <div>
              <label className="mb-1 block font-mono text-xs font-medium text-text2">Description</label>
              <textarea
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="Describe the bug..."
                rows={3}
                className="w-full rounded-lg border border-[var(--color-border-2)] bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm text-text outline-none placeholder:text-text3 focus:border-accent"
              />
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div>
                <label className="mb-1 block font-mono text-xs font-medium text-text2">Priority</label>
                <select
                  value={newPriority}
                  onChange={(e) => setNewPriority(e.target.value)}
                  className={`w-full ${selectCls}`}
                >
                  {PRIORITY_OPTIONS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
              <Input label="Thread ID (optional)" value={newThreadId} onChange={(e) => setNewThreadId(e.target.value)} placeholder="thr_..." />
              <Input label="Trace ID (optional)" value={newTraceId} onChange={(e) => setNewTraceId(e.target.value)} placeholder="trc_..." />
            </div>
            <div className="flex justify-end">
              <Button onClick={() => createMutation.mutate()} disabled={!newTitle.trim() || createMutation.isPending}>
                {createMutation.isPending ? "Creating..." : "Create Bug"}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Bug list + detail */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_380px]">
        <div className="space-y-2">
          {items.length === 0 && (
            <p className="py-8 text-center font-mono text-xs text-text3">No bugs found.</p>
          )}
          {items.map((bug) => (
            <button
              key={bug.id}
              onClick={() => setSelectedId(bug.id)}
              className={`w-full rounded-lg border p-3 text-left transition-colors ${
                selectedId === bug.id
                  ? "border-accent/30 bg-accent-dim"
                  : "border-[var(--color-border)] bg-[var(--color-surface)] hover:border-[var(--color-border-2)] hover:bg-surface-2"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-text truncate">{bug.title}</div>
                  {bug.description && (
                    <div className="mt-0.5 line-clamp-1 font-mono text-xs text-text3">{bug.description}</div>
                  )}
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Badge variant={priorityBadge[bug.priority]}>{bug.priority}</Badge>
                  <Badge variant={statusBadge[bug.status]}>{bug.status.replace("_", " ")}</Badge>
                </div>
              </div>
              <div className="mt-1.5 flex gap-3 font-mono text-[10px] text-text3">
                <span>{bug.id}</span>
                <span>{new Date(bug.created_at).toLocaleDateString()}</span>
                {bug.assignee_agent && <span>assigned: {bug.assignee_agent}</span>}
              </div>
            </button>
          ))}
        </div>

        {/* Detail panel */}
        <div>
          {selected ? (
            <Card className="sticky top-4" header={
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Bug Detail</span>
                <button onClick={() => setSelectedId("")} className="text-text3 hover:text-text">
                  <X size={16} />
                </button>
              </div>
            }>
              <div className="space-y-3">
                <div>
                  <div className="font-semibold text-text">{selected.title}</div>
                  <div className="mt-1 flex gap-2">
                    <Badge variant={statusBadge[selected.status]}>{selected.status.replace("_", " ")}</Badge>
                    <Badge variant={priorityBadge[selected.priority]}>{selected.priority}</Badge>
                  </div>
                </div>
                {selected.description && (
                  <p className="whitespace-pre-wrap font-mono text-xs text-text2">{selected.description}</p>
                )}
                <div className="space-y-1 font-mono text-[10px] text-text3">
                  <div>ID: {selected.id}</div>
                  <div>Reporter: {selected.reporter_id ?? "—"}</div>
                  <div>Assignee: {selected.assignee_agent ?? "—"}</div>
                  {selected.thread_id && <div>Thread: {selected.thread_id}</div>}
                  {selected.trace_id && <div>Trace: {selected.trace_id}</div>}
                  <div>Created: {new Date(selected.created_at).toLocaleString()}</div>
                  <div>Updated: {new Date(selected.updated_at).toLocaleString()}</div>
                </div>

                {/* Status transition */}
                {nextStatus[selected.status] && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<ArrowRight size={14} />}
                    onClick={() => updateMutation.mutate({ id: selected.id, payload: { status: nextStatus[selected.status] } })}
                    disabled={updateMutation.isPending}
                  >
                    Move to {nextStatus[selected.status].replace("_", " ")}
                  </Button>
                )}

                {/* Edit priority */}
                <div>
                  <label className="mb-1 block font-mono text-[10px] font-medium text-text3">Change Priority</label>
                  <div className="flex flex-wrap gap-1">
                    {PRIORITY_OPTIONS.map((p) => (
                      <Button
                        key={p}
                        variant={selected.priority === p ? "primary" : "ghost"}
                        size="sm"
                        onClick={() => updateMutation.mutate({ id: selected.id, payload: { priority: p } })}
                      >
                        {p}
                      </Button>
                    ))}
                  </div>
                </div>

                {/* Edit assignee */}
                <div>
                  <label className="mb-1 block font-mono text-[10px] font-medium text-text3">Assign Agent</label>
                  <div className="flex flex-wrap gap-1">
                    {["main", "researcher", "planner", "coder", "tester", "lintfixer", "api_guardian", "data_migrator", "web_builder", "security_reviewer", "docs_keeper", "release_ops"].map((a) => (
                      <Button
                        key={a}
                        variant={selected.assignee_agent === a ? "primary" : "ghost"}
                        size="sm"
                        onClick={() => updateMutation.mutate({ id: selected.id, payload: { assignee_agent: a } })}
                      >
                        {a}
                      </Button>
                    ))}
                  </div>
                </div>

                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => removeMutation.mutate(selected.id)}
                  disabled={removeMutation.isPending}
                >
                  Delete Bug
                </Button>
              </div>
            </Card>
          ) : (
            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-8 text-center font-mono text-xs text-text3">
              Select a bug to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
