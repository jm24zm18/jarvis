import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Unlock, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { getSystemStatus, reloadAgents, resetDatabase, setLockdown } from "../../../api/endpoints";
import { useWebSocket } from "../../../hooks/useWebSocket";
import Header from "../../../components/layout/Header";
import Button from "../../../components/ui/Button";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";

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

  return (
    <div>
      <Header title="System Dashboard" subtitle="Health, providers, queues, scheduler" />

      {/* Stat row */}
      <div className="mb-6 grid grid-cols-2 divide-x divide-[var(--color-border)] rounded-lg border border-[var(--color-border)] lg:grid-cols-4">
        <div className="px-4 py-3">
          <p className="text-[10px] font-mono uppercase tracking-widest text-text3">Lockdown</p>
          <p className="mt-1 font-mono text-lg font-semibold text-text">
            {lockdown ? "ON" : "OFF"}
          </p>
          <div className="mt-1">
            <Badge variant={lockdown ? "danger" : "success"}>
              {lockdown ? "Locked" : "Operational"}
            </Badge>
          </div>
        </div>

        <div className="px-4 py-3">
          <p className="text-[10px] font-mono uppercase tracking-widest text-text3">
            Primary ({primaryProviderName})
          </p>
          <p className="mt-1 font-mono text-lg font-semibold text-text">
            {data?.providers.primary ? "UP" : "DOWN"}
          </p>
          <div className="mt-1">
            <Badge variant={data?.providers.primary ? "success" : "danger"}>
              {data?.providers.primary ? "Healthy" : "Unreachable"}
            </Badge>
          </div>
        </div>

        <div className="px-4 py-3">
          <p className="text-[10px] font-mono uppercase tracking-widest text-text3">
            Fallback ({fallbackProviderName})
          </p>
          <p className="mt-1 font-mono text-lg font-semibold text-text">
            {data?.providers.fallback ? "UP" : "DOWN"}
          </p>
          <div className="mt-1">
            <Badge variant={data?.providers.fallback ? "success" : "warning"}>
              {data?.providers.fallback ? "Available" : "Unavailable"}
            </Badge>
          </div>
        </div>

        <div className="px-4 py-3">
          <p className="text-[10px] font-mono uppercase tracking-widest text-text3">
            Scheduler Deferred
          </p>
          <p className="mt-1 font-mono text-lg font-semibold text-text">
            {data?.scheduler.deferred_total ?? 0}
          </p>
          <div className="mt-1">
            <Badge variant={(data?.scheduler.deferred_total ?? 0) > 0 ? "warning" : "success"}>
              {(data?.scheduler.deferred_total ?? 0) > 0 ? "Backlogged" : "Clear"}
            </Badge>
          </div>
        </div>
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
        <Card header={<span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Queue Depths</span>}>
          {queueDepths.length === 0 ? (
            <p className="text-sm text-text3">No queues reported.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Queue</TableHead>
                  <TableHead>Depth</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {queueDepths.map(([name, depth]) => {
                  const numDepth = Number(depth);
                  return (
                    <TableRow key={name}>
                      <TableCell className="font-mono text-xs">{name}</TableCell>
                      <TableCell>
                        <Badge variant={numDepth > 10 ? "warning" : "default"}>
                          {numDepth}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </Card>

        <Card header={<span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Scheduler Backlog</span>}>
          <pre className="max-h-80 overflow-auto rounded bg-surface-2 p-3 font-mono text-xs text-text2">
            {JSON.stringify(data?.scheduler ?? {}, null, 2)}
          </pre>
        </Card>
      </div>
    </div>
  );
}
