import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { MessagesSquare, Lock, Unlock } from "lucide-react";
import { getThread, listMessages, listThreads, patchThread } from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Card from "../../../components/ui/Card";
import Pagination from "../../../components/ui/Pagination";

const PAGE_SIZE = 20;

function statusBadgeVariant(status: string): "success" | "warning" | "danger" | "default" {
  switch (status) {
    case "open":
      return "success";
    case "closed":
      return "danger";
    case "pending":
      return "warning";
    default:
      return "default";
  }
}

export default function AdminThreadsPage() {
  const [selectedThreadId, setSelectedThreadId] = useState("");
  const [page, setPage] = useState(1);
  const threads = useQuery({ queryKey: ["threads-admin"], queryFn: () => listThreads(true) });
  const detail = useQuery({
    queryKey: ["thread", selectedThreadId],
    queryFn: () => getThread(selectedThreadId),
    enabled: !!selectedThreadId,
  });
  const messages = useQuery({
    queryKey: ["thread-messages", selectedThreadId],
    queryFn: () => listMessages(selectedThreadId),
    enabled: !!selectedThreadId,
  });

  const statusMutation = useMutation({
    mutationFn: ({ threadId, status }: { threadId: string; status: string }) =>
      patchThread(threadId, { status }),
    onSuccess: () => {
      void threads.refetch();
      void detail.refetch();
    },
  });

  const allThreads = threads.data?.items ?? [];
  const pagedThreads = allThreads.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const messageItems = messages.data?.items ?? [];

  return (
    <div>
      <Header
        title="Thread Manager"
        subtitle="All thread channels, statuses, and message history"
        icon={<MessagesSquare className="h-6 w-6" />}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.15fr_1fr]">
        {/* Thread List */}
        <Card
          header={
            <div className="flex items-center justify-between">
              <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                Threads
              </span>
              <Badge variant="info">{allThreads.length} total</Badge>
            </div>
          }
          footer={
            <Pagination page={page} pageSize={PAGE_SIZE} total={allThreads.length} onPage={setPage} />
          }
        >
          <div className="space-y-2">
            {pagedThreads.length === 0 && (
              <p className="py-8 text-center text-sm text-[var(--text-muted)]">
                No threads found.
              </p>
            )}
            {pagedThreads.map((item) => (
              <div
                key={item.id}
                onClick={() => setSelectedThreadId(item.id)}
                className={`cursor-pointer rounded-lg border px-3 py-2.5 transition-colors ${
                  selectedThreadId === item.id
                    ? "border-ember/40 bg-ember/5"
                    : "border-[var(--border-default)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-mist)]"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MessagesSquare className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                    <span className="text-sm font-medium text-[var(--text-primary)]">
                      {item.channel_type}
                    </span>
                  </div>
                  <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                </div>
                <div className="mt-1 flex items-center justify-between pl-5">
                  <span className="truncate text-xs text-[var(--text-muted)]">{item.id}</span>
                  <span className="ml-2 shrink-0 text-xs text-[var(--text-muted)]">
                    {item.updated_at}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Thread Detail + Messages */}
        <div className="space-y-4">
          <Card
            header={
              <div className="flex items-center gap-2">
                <MessagesSquare className="h-4 w-4 text-[var(--text-muted)]" />
                <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                  Thread Detail
                </span>
              </div>
            }
          >
            {!selectedThreadId ? (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <MessagesSquare className="mb-3 h-10 w-10 text-[var(--text-muted)]" />
                <p className="text-sm text-[var(--text-muted)]">
                  Select a thread to view details
                </p>
              </div>
            ) : detail.isLoading ? (
              <p className="py-6 text-center text-sm text-[var(--text-muted)]">Loading...</p>
            ) : detail.data ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-xs text-[var(--text-muted)]">Thread ID</span>
                    <p className="mt-0.5 truncate text-sm font-medium text-[var(--text-primary)]">
                      {detail.data.id}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs text-[var(--text-muted)]">Channel</span>
                    <p className="mt-0.5 text-sm font-medium text-[var(--text-primary)]">
                      {detail.data.channel_type}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs text-[var(--text-muted)]">Status</span>
                    <div className="mt-0.5">
                      <Badge variant={statusBadgeVariant(detail.data.status)}>
                        {detail.data.status}
                      </Badge>
                    </div>
                  </div>
                </div>
                <div className="border-t border-[var(--border-default)] pt-3">
                  <Button
                    variant={detail.data.status === "open" ? "danger" : "secondary"}
                    size="sm"
                    icon={
                      detail.data.status === "open" ? (
                        <Lock className="h-3.5 w-3.5" />
                      ) : (
                        <Unlock className="h-3.5 w-3.5" />
                      )
                    }
                    onClick={() =>
                      statusMutation.mutate({
                        threadId: detail.data.id,
                        status: detail.data.status === "open" ? "closed" : "open",
                      })
                    }
                    disabled={statusMutation.isPending}
                  >
                    {detail.data.status === "open" ? "Close Thread" : "Reopen Thread"}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>

          {/* Messages */}
          {selectedThreadId && (
            <Card
              header={
                <div className="flex items-center justify-between">
                  <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                    Messages
                  </span>
                  <Badge variant="default">{messageItems.length} messages</Badge>
                </div>
              }
            >
              <div className="max-h-[28rem] space-y-2 overflow-auto">
                {messageItems.length === 0 ? (
                  <p className="py-6 text-center text-sm text-[var(--text-muted)]">
                    No messages in this thread.
                  </p>
                ) : (
                  messageItems.map((m) => (
                    <div
                      key={m.id}
                      className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-3 py-2"
                    >
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-semibold text-[var(--text-secondary)]">
                          {m.speaker ?? m.role}
                        </span>
                        <span className="text-[11px] text-[var(--text-muted)]">
                          {m.created_at ?? ""}
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm text-[var(--text-primary)]">
                        {m.content}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
