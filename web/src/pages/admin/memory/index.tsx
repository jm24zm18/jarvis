import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, Database, Cpu } from "lucide-react";
import { listMemory, memoryStats } from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Pagination from "../../../components/ui/Pagination";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";

const PAGE_SIZE = 25;

export default function AdminMemoryPage() {
  const [q, setQ] = useState("");
  const [threadId, setThreadId] = useState("");
  const [page, setPage] = useState(1);

  const stats = useQuery({ queryKey: ["memory-stats"], queryFn: memoryStats });
  const items = useQuery({
    queryKey: ["memory", q, threadId],
    queryFn: () => listMemory(q, threadId),
  });

  const allItems = items.data?.items ?? [];
  const pagedItems = allItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const totalItems = stats.data?.total_items ?? 0;
  const embeddedItems = stats.data?.embedded_items ?? 0;
  const coveragePct = stats.data?.embedding_coverage_pct ?? 0;
  const unembedded = totalItems - embeddedItems;

  return (
    <div>
      <Header title="Memory" subtitle="Semantic + FTS memory search with coverage metrics" />

      {/* Stats cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/30">
              <Database className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Total Items
              </p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">{totalItems}</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
              <Cpu className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Embedded Items
              </p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">
                {embeddedItems}
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-purple-100 dark:bg-purple-900/30">
              <Brain className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                Embedding Coverage
              </p>
              <div className="mt-2">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-display text-lg text-[var(--text-primary)]">
                    {coveragePct}%
                  </span>
                  {unembedded > 0 ? (
                    <Badge variant="warning">{unembedded} pending</Badge>
                  ) : (
                    <Badge variant="success">Complete</Badge>
                  )}
                </div>
                <div className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--bg-mist)]">
                  <div
                    className="h-full rounded-full bg-purple-500 transition-all"
                    style={{ width: `${coveragePct}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Search controls */}
      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            label="Search Text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Semantic or keyword search"
          />
          <Input
            label="Thread ID"
            value={threadId}
            onChange={(e) => setThreadId(e.target.value)}
            placeholder="Optional thread filter"
          />
          <div className="flex items-end">
            <Button
              icon={<Brain className="h-4 w-4" />}
              className="w-full"
              onClick={() => {
                setPage(1);
                void items.refetch();
              }}
            >
              Search
            </Button>
          </div>
          <div className="flex items-end">
            <Button
              variant="secondary"
              icon={<Database className="h-4 w-4" />}
              className="w-full"
              onClick={() => void stats.refetch()}
            >
              Refresh Stats
            </Button>
          </div>
        </div>
      </Card>

      {/* Memory items table */}
      <Card
        header={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-[var(--text-muted)]" />
              <h3 className="font-display text-base text-[var(--text-primary)]">Memory Items</h3>
            </div>
            <Badge variant="default">{allItems.length} results</Badge>
          </div>
        }
        footer={
          <Pagination page={page} pageSize={PAGE_SIZE} total={allItems.length} onPage={setPage} />
        }
      >
        <div className="-mx-4 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-default)] text-left">
                <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                  ID
                </th>
                <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                  Thread
                </th>
                <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                  Text
                </th>
              </tr>
            </thead>
            <tbody>
              {pagedItems.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-[var(--border-default)] transition hover:bg-[var(--bg-mist)]"
                >
                  <td className="whitespace-nowrap px-4 py-2.5 align-top font-mono text-xs text-[var(--text-muted)]">
                    {item.id}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 align-top">
                    {item.thread_id ? (
                      <Badge variant="info">{item.thread_id}</Badge>
                    ) : (
                      <span className="text-xs text-[var(--text-muted)]">-</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                    {item.text}
                  </td>
                </tr>
              ))}
              {pagedItems.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">
                    No memory items found. Try a different search query.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
