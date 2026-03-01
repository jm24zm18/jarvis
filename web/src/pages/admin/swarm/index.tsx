import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Rocket, RefreshCcw, Send, Trash2 } from "lucide-react";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Input from "../../../components/ui/Input";
import {
  cleanupSwarmTask,
  createSwarmTask,
  listSwarmTasks,
  nudgeSwarmTask,
} from "../../../api/endpoints";
import type { DevSwarmTask } from "../../../types";
import { formatTimestampHuman } from "../../../lib/format";
import { useWebSocket } from "../../../hooks/useWebSocket";

function statusVariant(status: string): "default" | "warning" | "success" | "danger" | "info" {
  if (status === "ready_for_review") return "success";
  if (status === "needs_attention") return "warning";
  if (status === "failed") return "danger";
  if (status === "running" || status === "queued") return "info";
  return "default";
}

export default function AdminSwarmPage() {
  const qc = useQueryClient();
  const [taskType, setTaskType] = useState<"feature" | "bugfix" | "refactor">("feature");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [nudgeText, setNudgeText] = useState("");
  const [removeWorktrees, setRemoveWorktrees] = useState(false);

  const tasks = useQuery({
    queryKey: ["swarm-tasks"],
    queryFn: () => listSwarmTasks({ limit: 100 }),
  });

  const rows = useMemo(() => tasks.data?.items ?? [], [tasks.data]);
  const selected = useMemo(
    () => rows.find((row) => row.id === selectedId) ?? rows[0] ?? null,
    [rows, selectedId],
  );

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
    if (!selected) setSelectedId("");
  }, [selected, selectedId]);

  const createMutation = useMutation({
    mutationFn: () =>
      createSwarmTask({
        description,
        task_type: taskType,
        model: model.trim() || undefined,
      }),
    onSuccess: async (payload) => {
      setDescription("");
      setModel("");
      setSelectedId(payload.item.id);
      await qc.invalidateQueries({ queryKey: ["swarm-tasks"] });
    },
  });

  const nudgeMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("Select a task first");
      return nudgeSwarmTask(selected.id, nudgeText);
    },
    onSuccess: async () => {
      setNudgeText("");
      await qc.invalidateQueries({ queryKey: ["swarm-tasks"] });
    },
  });

  const cleanupMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("Select a task first");
      return cleanupSwarmTask(selected.id, removeWorktrees);
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["swarm-tasks"] });
    },
  });

  const ws = useWebSocket((payload) => {
    const type = String(payload.type ?? "");
    if (!type.startsWith("system.swarm.")) return;
    void qc.invalidateQueries({ queryKey: ["swarm-tasks"] });
  });

  useEffect(() => {
    ws.subscribeSystem();
  }, [ws]);

  const checks = (selected?.checks as Record<string, unknown> | undefined) ?? {};
  const gates = (checks.gates as Record<string, unknown> | undefined) ?? {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Header
          title="DevSwarm"
          subtitle="Create, monitor, and control DevSwarm tasks"
          icon={<Rocket className="h-6 w-6" />}
        />
        <Button
          variant="secondary"
          icon={<RefreshCcw className={`h-4 w-4 ${tasks.isFetching ? "animate-spin" : ""}`} />}
          onClick={() => void tasks.refetch()}
        >
          Refresh
        </Button>
      </div>

      <Card
        header={
          <span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">
            Create Task
          </span>
        }
      >
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
          <Input
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Implement feature X"
          />
          <div>
            <label className="mb-1 block text-xs text-text3">Type</label>
            <select
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-text"
              value={taskType}
              onChange={(e) => setTaskType(e.target.value as "feature" | "bugfix" | "refactor")}
            >
              <option value="feature">feature</option>
              <option value="bugfix">bugfix</option>
              <option value="refactor">refactor</option>
            </select>
          </div>
          <Input
            label="Model (optional)"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="qwen2.5-coder-7b-instruct"
          />
          <div className="lg:col-span-2 flex items-end">
            <Button
              className="w-full"
              icon={<Rocket className="h-4 w-4" />}
              disabled={!description.trim() || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? "Creating..." : "Create Task"}
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Card
          header={
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">
                Task Registry
              </span>
              <Badge variant="info">{rows.length} tasks</Badge>
            </div>
          }
        >
          <div className="-mx-4 overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left">
                  <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-widest text-text3">Task</th>
                  <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-widest text-text3">Status</th>
                  <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-widest text-text3">Branch</th>
                  <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-widest text-text3">PR</th>
                  <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-widest text-text3">Attempts</th>
                  <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-widest text-text3">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => (
                  <tr
                    key={item.id}
                    className={`cursor-pointer border-b border-[var(--color-border)] ${
                      selected?.id === item.id ? "bg-surface-2" : "hover:bg-surface-2"
                    }`}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <td className="px-4 py-2">
                      <div className="font-mono text-xs text-text">{item.id}</div>
                      <div className="text-xs text-text3">{item.task_type}</div>
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-text3">{item.branch}</td>
                    <td className="px-4 py-2 text-xs text-text3">
                      {item.pr_url ? (
                        <a href={item.pr_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                          #{item.pr_number ?? "?"}
                        </a>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs text-text3">
                      {item.attempt}/{item.max_attempts}
                    </td>
                    <td className="px-4 py-2 text-xs text-text3">{formatTimestampHuman(item.updated_at)}</td>
                  </tr>
                ))}
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-sm text-text3">
                      No swarm tasks yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>

        <Card
          header={
            <span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">
              Task Details
            </span>
          }
        >
          {!selected ? (
            <p className="text-sm text-text3">Select a task to inspect and control it.</p>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <div className="font-mono text-xs text-text3">Description</div>
                <p className="text-text">{selected.description || "-"}</p>
              </div>
              <div className="grid grid-cols-1 gap-2">
                <div className="font-mono text-xs text-text3">Repo: {selected.repo_path}</div>
                <div className="font-mono text-xs text-text3">Worktree: {selected.worktree_path}</div>
                <div className="font-mono text-xs text-text3">Session: {selected.tmux_session}</div>
                <div className="font-mono text-xs text-text3">Model: {selected.model}</div>
                {selected.last_error ? (
                  <div className="rounded border border-danger/30 bg-danger-dim px-2 py-1 text-xs text-danger">
                    {selected.last_error}
                  </div>
                ) : null}
              </div>

              <div>
                <div className="mb-1 font-mono text-xs text-text3">Nudge Worker</div>
                <div className="flex gap-2">
                  <Input
                    value={nudgeText}
                    onChange={(e) => setNudgeText(e.target.value)}
                    placeholder="re-run tests"
                  />
                  <Button
                    icon={<Send className="h-4 w-4" />}
                    variant="secondary"
                    disabled={!nudgeText.trim() || nudgeMutation.isPending}
                    onClick={() => nudgeMutation.mutate()}
                  >
                    Nudge
                  </Button>
                </div>
              </div>

              <div className="rounded border border-[var(--color-border)] p-3">
                <div className="mb-2 font-mono text-xs text-text3">Cleanup</div>
                <label className="mb-2 flex items-center gap-2 text-xs text-text3">
                  <input
                    type="checkbox"
                    checked={removeWorktrees}
                    onChange={(e) => setRemoveWorktrees(e.target.checked)}
                  />
                  Remove worktree directory
                </label>
                <Button
                  variant="danger"
                  icon={<Trash2 className="h-4 w-4" />}
                  disabled={cleanupMutation.isPending}
                  onClick={() => cleanupMutation.mutate()}
                >
                  Cleanup Task
                </Button>
              </div>

              <div>
                <div className="mb-1 font-mono text-xs text-text3">Gates</div>
                <div className="space-y-1">
                  {Object.entries(gates).length === 0 ? (
                    <p className="text-xs text-text3">No checks available yet.</p>
                  ) : (
                    Object.entries(gates).map(([name, ok]) => (
                      <div key={name} className="flex items-center justify-between text-xs">
                        <span className="font-mono text-text3">{name}</span>
                        <Badge variant={ok ? "success" : "warning"}>{ok ? "pass" : "fail"}</Badge>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
