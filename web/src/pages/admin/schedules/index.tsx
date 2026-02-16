import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Clock, Play, Pause, Plus } from "lucide-react";
import {
  createSchedule,
  listDispatches,
  listSchedules,
  updateSchedule,
} from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Card from "../../../components/ui/Card";
import Pagination from "../../../components/ui/Pagination";

const PAGE_SIZE = 20;

export default function AdminSchedulesPage() {
  const [selectedScheduleId, setSelectedScheduleId] = useState("");
  const [cronExpr, setCronExpr] = useState("@every:60");
  const [threadId, setThreadId] = useState("");
  const [payloadJson, setPayloadJson] = useState('{"type":"tick"}');
  const [page, setPage] = useState(1);

  const schedules = useQuery({ queryKey: ["schedules"], queryFn: listSchedules });
  const dispatches = useQuery({
    queryKey: ["dispatches", selectedScheduleId],
    queryFn: () => listDispatches(selectedScheduleId),
    enabled: !!selectedScheduleId,
  });

  const createMutation = useMutation({
    mutationFn: () => createSchedule({ cron_expr: cronExpr, thread_id: threadId, payload_json: payloadJson }),
    onSuccess: () => void schedules.refetch(),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => updateSchedule(id, { enabled }),
    onSuccess: () => void schedules.refetch(),
  });

  const scheduleRows = useMemo(() => schedules.data?.items ?? [], [schedules.data]);
  const pagedRows = scheduleRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const dispatchItems = dispatches.data?.items ?? [];

  return (
    <div>
      <Header
        title="Schedules"
        subtitle="Create and manage scheduled tasks with dispatch history"
        icon={<Clock className="h-6 w-6" />}
      />

      {/* Create Schedule Form */}
      <Card
        className="mb-6"
        header={
          <div className="flex items-center gap-2">
            <Plus className="h-4 w-4 text-[var(--text-muted)]" />
            <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
              Create Schedule
            </span>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Input
            label="Cron Expression"
            value={cronExpr}
            onChange={(e) => setCronExpr(e.target.value)}
            placeholder="@every:60"
          />
          <Input
            label="Thread ID"
            value={threadId}
            onChange={(e) => setThreadId(e.target.value)}
            placeholder="thread_id"
          />
          <Input
            label="Payload JSON"
            value={payloadJson}
            onChange={(e) => setPayloadJson(e.target.value)}
            placeholder='{"type":"tick"}'
          />
          <div className="flex items-end">
            <Button
              icon={<Plus className="h-4 w-4" />}
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending || !cronExpr}
              className="w-full"
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.2fr_1fr]">
        {/* Schedule List */}
        <Card
          header={
            <div className="flex items-center justify-between">
              <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                All Schedules
              </span>
              <Badge variant="info">{scheduleRows.length} total</Badge>
            </div>
          }
          footer={
            <Pagination page={page} pageSize={PAGE_SIZE} total={scheduleRows.length} onPage={setPage} />
          }
        >
          <div className="space-y-2">
            {pagedRows.length === 0 && (
              <p className="py-8 text-center text-sm text-[var(--text-muted)]">
                No schedules yet. Create one above.
              </p>
            )}
            {pagedRows.map((item) => (
              <div
                key={item.id}
                className={`group flex items-center justify-between rounded-lg border px-3 py-2.5 transition-colors ${
                  selectedScheduleId === item.id
                    ? "border-ember/40 bg-ember/5"
                    : "border-[var(--border-default)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-mist)]"
                }`}
              >
                <div
                  className="flex-1 cursor-pointer"
                  onClick={() => setSelectedScheduleId(item.id)}
                >
                  <div className="flex items-center gap-2">
                    <Clock className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                    <code className="text-xs font-semibold text-[var(--text-primary)]">
                      {item.cron_expr}
                    </code>
                    <Badge variant={item.enabled ? "success" : "warning"}>
                      {item.enabled ? "Active" : "Paused"}
                    </Badge>
                  </div>
                  <p className="mt-1 truncate pl-5 text-xs text-[var(--text-muted)]">
                    {item.id}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={
                    item.enabled ? (
                      <Pause className="h-3.5 w-3.5" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )
                  }
                  onClick={() => toggleMutation.mutate({ id: item.id, enabled: !item.enabled })}
                  disabled={toggleMutation.isPending}
                >
                  {item.enabled ? "Pause" : "Resume"}
                </Button>
              </div>
            ))}
          </div>
        </Card>

        {/* Dispatch History */}
        <Card
          header={
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-[var(--text-muted)]" />
              <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                Dispatch History
              </span>
              {selectedScheduleId && (
                <Badge variant="default">{dispatchItems.length} dispatches</Badge>
              )}
            </div>
          }
        >
          {!selectedScheduleId ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Clock className="mb-3 h-10 w-10 text-[var(--text-muted)]" />
              <p className="text-sm text-[var(--text-muted)]">
                Select a schedule to view its dispatch history
              </p>
            </div>
          ) : dispatches.isLoading ? (
            <p className="py-8 text-center text-sm text-[var(--text-muted)]">Loading dispatches...</p>
          ) : dispatchItems.length === 0 ? (
            <p className="py-8 text-center text-sm text-[var(--text-muted)]">
              No dispatches recorded yet.
            </p>
          ) : (
            <div className="max-h-[32rem] space-y-2 overflow-auto">
              {dispatchItems.map((d, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-3 py-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text-primary)]">
                      #{idx + 1}
                    </span>
                    <span className="text-xs text-[var(--text-muted)]">
                      {d.dispatched_at ?? ""}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-[var(--text-secondary)]">
                    Due: {d.due_at}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
