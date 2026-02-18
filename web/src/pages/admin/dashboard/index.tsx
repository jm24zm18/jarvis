import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Unlock, Server, Calendar, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { getSystemStatus, reloadAgents, resetDatabase, setLockdown } from "../../../api/endpoints";
import { useWebSocket } from "../../../hooks/useWebSocket";
import Header from "../../../components/layout/Header";
import Button from "../../../components/ui/Button";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";

export default function AdminDashboardPage() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["system-status"],
    queryFn: getSystemStatus,
    refetchInterval: 10000,
  });
  const toggleLockdown = useMutation({
    mutationFn: (next: boolean) => setLockdown(next, "web_ui"),
    onSuccess: () => void status.refetch(),
  });
  const reloadAgentsMutation = useMutation({
    mutationFn: reloadAgents,
  });
  const resetDatabaseMutation = useMutation({
    mutationFn: resetDatabase,
    onSuccess: () => void queryClient.invalidateQueries(),
  });
  const ws = useWebSocket((event) => {
    if (String(event.type ?? "").startsWith("system.")) void status.refetch();
  });

  useEffect(() => {
    ws.subscribeSystem();
  }, [ws]);

  const data = status.data;
  const lockdown = data?.system.lockdown === 1;
  const primaryProviderName = data?.providers.primary_name ?? "primary";
  const fallbackProviderName = data?.providers.fallback_name ?? "fallback";
  const queueDepths = Object.entries(data?.queue_depths ?? {});
  const maxDepth = Math.max(1, ...queueDepths.map(([, d]) => Number(d)));

  return (
    <div>
      <Header title="System Dashboard" subtitle="Health, providers, queues, scheduler" />

      {/* Stat cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="overflow-hidden">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Lockdown
              </p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">
                {lockdown ? "ON" : "OFF"}
              </p>
            </div>
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                lockdown ? "bg-red-100 dark:bg-red-900/30" : "bg-emerald-100 dark:bg-emerald-900/30"
              }`}
            >
              {lockdown ? (
                <Lock className="h-5 w-5 text-red-600 dark:text-red-400" />
              ) : (
                <Unlock className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              )}
            </div>
          </div>
          <div className="mt-2">
            <Badge variant={lockdown ? "danger" : "success"}>
              {lockdown ? "System locked" : "Operational"}
            </Badge>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Primary Provider ({primaryProviderName})
              </p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">
                {data?.providers.primary ? "UP" : "DOWN"}
              </p>
            </div>
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                data?.providers.primary
                  ? "bg-emerald-100 dark:bg-emerald-900/30"
                  : "bg-red-100 dark:bg-red-900/30"
              }`}
            >
              <Server
                className={`h-5 w-5 ${
                  data?.providers.primary
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-600 dark:text-red-400"
                }`}
              />
            </div>
          </div>
          <div className="mt-2">
            <Badge variant={data?.providers.primary ? "success" : "danger"}>
              {data?.providers.primary ? "Healthy" : "Unreachable"}
            </Badge>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Fallback Provider ({fallbackProviderName})
              </p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">
                {data?.providers.fallback ? "UP" : "DOWN"}
              </p>
            </div>
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                data?.providers.fallback
                  ? "bg-emerald-100 dark:bg-emerald-900/30"
                  : "bg-amber-100 dark:bg-amber-900/30"
              }`}
            >
              <Server
                className={`h-5 w-5 ${
                  data?.providers.fallback
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-amber-600 dark:text-amber-400"
                }`}
              />
            </div>
          </div>
          <div className="mt-2">
            <Badge variant={data?.providers.fallback ? "success" : "warning"}>
              {data?.providers.fallback ? "Available" : "Unavailable"}
            </Badge>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Scheduler Deferred
              </p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">
                {data?.scheduler.deferred_total ?? 0}
              </p>
            </div>
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                (data?.scheduler.deferred_total ?? 0) > 0
                  ? "bg-amber-100 dark:bg-amber-900/30"
                  : "bg-emerald-100 dark:bg-emerald-900/30"
              }`}
            >
              <Calendar
                className={`h-5 w-5 ${
                  (data?.scheduler.deferred_total ?? 0) > 0
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-emerald-600 dark:text-emerald-400"
                }`}
              />
            </div>
          </div>
          <div className="mt-2">
            <Badge variant={(data?.scheduler.deferred_total ?? 0) > 0 ? "warning" : "success"}>
              {(data?.scheduler.deferred_total ?? 0) > 0 ? "Backlogged" : "Clear"}
            </Badge>
          </div>
        </Card>
      </div>

      {/* Actions */}
      <div className="mb-6 flex items-center gap-3">
        <Button
          variant={lockdown ? "danger" : "secondary"}
          icon={lockdown ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
          onClick={() => toggleLockdown.mutate(!lockdown)}
          disabled={toggleLockdown.isPending || !data}
        >
          {lockdown ? "Disable Lockdown" : "Enable Lockdown"}
        </Button>
        <Button
          variant="secondary"
          icon={<RotateCcw className="h-4 w-4" />}
          onClick={() => {
            if (!window.confirm("Reload all agents from disk now?")) return;
            reloadAgentsMutation.mutate();
          }}
          disabled={reloadAgentsMutation.isPending}
        >
          Reload Agents
        </Button>
        <Button
          variant="danger"
          icon={<Trash2 className="h-4 w-4" />}
          onClick={() => {
            if (
              !window.confirm(
                "This will permanently delete all database data and cannot be undone. Continue?",
              )
            )
              return;
            resetDatabaseMutation.mutate();
          }}
          disabled={resetDatabaseMutation.isPending}
        >
          Reset Database
        </Button>
        <Button
          variant="ghost"
          icon={<RefreshCw className={`h-4 w-4 ${status.isFetching ? "animate-spin" : ""}`} />}
          onClick={() => void status.refetch()}
        >
          Refresh
        </Button>
      </div>

      {/* Queue depths + Scheduler backlog */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          header={
            <h3 className="font-display text-base text-[var(--text-primary)]">Queue Depths</h3>
          }
        >
          {queueDepths.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No queues reported.</p>
          ) : (
            <div className="space-y-3">
              {queueDepths.map(([name, depth]) => {
                const numDepth = Number(depth);
                const pct = Math.min(100, (numDepth / maxDepth) * 100);
                const isHigh = numDepth > maxDepth * 0.7;
                return (
                  <div key={name}>
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <span className="font-medium text-[var(--text-primary)]">{name}</span>
                      <Badge variant={isHigh ? "warning" : "default"}>{numDepth}</Badge>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--bg-mist)]">
                      <div
                        className={`h-full rounded-full transition-all ${
                          isHigh ? "bg-amber-500" : "bg-leaf"
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <Card
          header={
            <h3 className="font-display text-base text-[var(--text-primary)]">
              Scheduler Backlog
            </h3>
          }
        >
          <pre className="max-h-80 overflow-auto rounded-lg bg-[var(--bg-mist)] p-3 text-xs text-[var(--text-secondary)]">
            {JSON.stringify(data?.scheduler ?? {}, null, 2)}
          </pre>
        </Card>
      </div>
    </div>
  );
}
