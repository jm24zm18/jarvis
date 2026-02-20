import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Database, Cpu } from "lucide-react";
import {
  listMemory,
  memoryConsistencyReport,
  memoryReviewConflicts,
  memoryStateFailures,
  memoryStateGraph,
  memoryStateStats,
  memoryStats,
  resolveMemoryReview,
  runMemoryMaintenance,
} from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Pagination from "../../../components/ui/Pagination";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";

const PAGE_SIZE = 25;

export default function AdminMemoryPage() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [threadId, setThreadId] = useState("");
  const [page, setPage] = useState(1);
  const [consistencyThreadId, setConsistencyThreadId] = useState("");
  const [consistencyFrom, setConsistencyFrom] = useState("");
  const [consistencyTo, setConsistencyTo] = useState("");
  const [failureQuery, setFailureQuery] = useState("");
  const [graphUid, setGraphUid] = useState("");

  const stats = useQuery({ queryKey: ["memory-stats"], queryFn: memoryStats });
  const stateStats = useQuery({ queryKey: ["memory-state-stats"], queryFn: memoryStateStats });
  const maintenance = useMutation({
    mutationFn: runMemoryMaintenance,
    onSuccess: () => {
      void stats.refetch();
      void stateStats.refetch();
      void items.refetch();
    },
  });
  const items = useQuery({
    queryKey: ["memory", q, threadId],
    queryFn: () => listMemory(q, threadId),
  });
  const consistency = useQuery({
    queryKey: ["memory-consistency", consistencyThreadId, consistencyFrom, consistencyTo],
    queryFn: () =>
      memoryConsistencyReport({
        limit: 40,
        thread_id: consistencyThreadId || undefined,
        from_ts: consistencyFrom || undefined,
        to_ts: consistencyTo || undefined,
      }),
  });
  const conflicts = useQuery({ queryKey: ["memory-conflicts"], queryFn: () => memoryReviewConflicts(50) });
  const failures = useQuery({
    queryKey: ["memory-failures", failureQuery],
    queryFn: () => memoryStateFailures({ similar_to: failureQuery || undefined, k: 12 }),
  });
  const graph = useQuery({
    queryKey: ["memory-graph", graphUid],
    enabled: !!graphUid.trim(),
    queryFn: () => memoryStateGraph(graphUid.trim(), 2),
  });
  const resolveMutation = useMutation({
    mutationFn: ({ uid, resolution }: { uid: string; resolution: string }) =>
      resolveMemoryReview(uid, resolution),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory-conflicts"] });
      void stateStats.refetch();
    },
  });

  const allItems = items.data?.items ?? [];
  const pagedItems = allItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const totalItems = stats.data?.total_items ?? 0;
  const embeddedItems = stats.data?.embedded_items ?? 0;
  const coveragePct = stats.data?.embedding_coverage_pct ?? 0;
  const unembedded = totalItems - embeddedItems;

  return (
    <div>
      <Header title="Memory" subtitle="Semantic + state memory governance and lifecycle" />

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/30">
              <Database className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Total Items</p>
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
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Embedded Items</p>
              <p className="mt-1 font-display text-2xl text-[var(--text-primary)]">{embeddedItems}</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-purple-100 dark:bg-purple-900/30">
              <Brain className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Embedding Coverage</p>
              <div className="mt-2">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-display text-lg text-[var(--text-primary)]">{coveragePct}%</span>
                  {unembedded > 0 ? <Badge variant="warning">{unembedded} pending</Badge> : <Badge variant="success">Complete</Badge>}
                </div>
                <div className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--bg-mist)]">
                  <div className="h-full rounded-full bg-purple-500 transition-all" style={{ width: `${coveragePct}%` }} />
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
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
            <Button variant="secondary" icon={<Database className="h-4 w-4" />} className="w-full" onClick={() => void stats.refetch()}>
              Refresh Stats
            </Button>
          </div>
          <div className="flex items-end">
            <Button
              variant="secondary"
              icon={<Cpu className="h-4 w-4" />}
              className="w-full"
              onClick={() => maintenance.mutate()}
              disabled={maintenance.isPending}
            >
              Run Maintenance
            </Button>
          </div>
        </div>
      </Card>

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
        footer={<Pagination page={page} pageSize={PAGE_SIZE} total={allItems.length} onPage={setPage} />}
      >
        <div className="-mx-4 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-default)] text-left">
                <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">ID</th>
                <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Thread</th>
                <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Text</th>
              </tr>
            </thead>
            <tbody>
              {pagedItems.map((item) => (
                <tr key={item.id} className="border-b border-[var(--border-default)] transition hover:bg-[var(--bg-mist)]">
                  <td className="whitespace-nowrap px-4 py-2.5 align-top font-mono text-xs text-[var(--text-muted)]">{item.id}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 align-top">
                    {item.thread_id ? <Badge variant="info">{item.thread_id}</Badge> : <span className="text-xs text-[var(--text-muted)]">-</span>}
                  </td>
                  <td className="px-4 py-2.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                    <div className="space-y-1.5">
                      <p className="whitespace-pre-wrap">{item.text}</p>
                      {item.metadata ? (
                        <details>
                          <summary className="cursor-pointer text-[11px] text-[var(--text-muted)]">details</summary>
                          <pre className="mt-1 overflow-auto rounded bg-[var(--bg-mist)] p-2 text-[11px]">
                            {JSON.stringify(item.metadata, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {pagedItems.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">No memory items found.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          header={
            <div className="flex items-center justify-between">
              <h3 className="font-display text-base text-[var(--text-primary)]">Conflict Review Queue</h3>
              <Badge variant="warning">{conflicts.data?.items.length ?? 0} open</Badge>
            </div>
          }
        >
          <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
            {(conflicts.data?.items ?? []).slice(0, 8).map((item) => (
              <li key={item.id} className="rounded border border-[var(--border-default)] p-2">
                <div className="font-mono text-xs">{item.uid}</div>
                <div className="text-xs text-[var(--text-muted)]">{item.reason}</div>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" onClick={() => resolveMutation.mutate({ uid: item.uid, resolution: "approved" })}>Approve</Button>
                  <Button size="sm" variant="secondary" onClick={() => resolveMutation.mutate({ uid: item.uid, resolution: "rejected" })}>Reject</Button>
                </div>
              </li>
            ))}
            {(conflicts.data?.items ?? []).length === 0 ? <li>No open conflicts.</li> : null}
          </ul>
        </Card>

        <Card
          header={
            <div className="flex items-center justify-between">
              <h3 className="font-display text-base text-[var(--text-primary)]">Tier and Archive Stats</h3>
              <Badge variant="info">archive {stateStats.data?.archive_items ?? 0}</Badge>
            </div>
          }
        >
          <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
            {(stateStats.data?.tiers ?? []).map((item) => (
              <li key={item.tier} className="flex items-center justify-between rounded border border-[var(--border-default)] px-2 py-1">
                <span>{item.tier}</span>
                <Badge variant="default">{item.count}</Badge>
              </li>
            ))}
            <li className="text-xs text-[var(--text-muted)]">Open conflicts: {stateStats.data?.open_conflicts ?? 0}</li>
          </ul>
        </Card>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card header={<h3 className="font-display text-base text-[var(--text-primary)]">Failure Lookup</h3>}>
          <div className="mb-3 flex gap-2">
            <Input label="Similar to" value={failureQuery} onChange={(e) => setFailureQuery(e.target.value)} placeholder="timeout or dns" />
            <div className="flex items-end">
              <Button variant="secondary" onClick={() => void failures.refetch()}>Search</Button>
            </div>
          </div>
          <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
            {(failures.data?.items ?? []).map((item) => (
              <li key={item.id} className="rounded border border-[var(--border-default)] p-2">
                <div className="text-xs">{item.phase} • {item.trace_id}</div>
                <div>{item.summary}</div>
              </li>
            ))}
            {(failures.data?.items ?? []).length === 0 ? <li>No failures found.</li> : null}
          </ul>
        </Card>

        <Card header={<h3 className="font-display text-base text-[var(--text-primary)]">Graph Traversal Preview</h3>}>
          <div className="mb-3 flex gap-2">
            <Input label="Root UID" value={graphUid} onChange={(e) => setGraphUid(e.target.value)} placeholder="st_..." />
            <div className="flex items-end">
              <Button variant="secondary" onClick={() => void graph.refetch()} disabled={!graphUid.trim()}>
                Load
              </Button>
            </div>
          </div>
          {graph.data ? (
            <div className="space-y-2 text-xs text-[var(--text-secondary)]">
              <div>nodes: {graph.data.nodes.length}</div>
              <div>edges: {graph.data.edges.length}</div>
              <pre className="max-h-48 overflow-auto rounded bg-[var(--bg-mist)] p-2">{JSON.stringify(graph.data, null, 2)}</pre>
            </div>
          ) : (
            <p className="text-sm text-[var(--text-muted)]">Enter a UID to preview graph traversal.</p>
          )}
        </Card>
      </div>

      <Card
        className="mt-6"
        header={
          <div className="flex items-center justify-between">
            <h3 className="font-display text-base text-[var(--text-primary)]">Consistency Reports</h3>
            <Badge variant="info">avg {Number(consistency.data?.avg_consistency ?? 1).toFixed(2)}</Badge>
          </div>
        }
      >
        <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Input
            label="Thread ID"
            value={consistencyThreadId}
            onChange={(e) => setConsistencyThreadId(e.target.value)}
            placeholder="optional"
          />
          <Input label="From (ISO)" value={consistencyFrom} onChange={(e) => setConsistencyFrom(e.target.value)} placeholder="2026-02-18T00:00:00+00:00" />
          <Input label="To (ISO)" value={consistencyTo} onChange={(e) => setConsistencyTo(e.target.value)} placeholder="2026-02-18T23:59:59+00:00" />
        </div>
        <div className="mb-3">
          <Button variant="secondary" onClick={() => void consistency.refetch()}>Apply Filters</Button>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-default)] text-left">
                <th className="px-2 py-2 text-xs uppercase tracking-wide text-[var(--text-muted)]">Thread</th>
                <th className="px-2 py-2 text-xs uppercase tracking-wide text-[var(--text-muted)]">Score</th>
                <th className="px-2 py-2 text-xs uppercase tracking-wide text-[var(--text-muted)]">Conflicts</th>
                <th className="px-2 py-2 text-xs uppercase tracking-wide text-[var(--text-muted)]">Created</th>
              </tr>
            </thead>
            <tbody>
              {(consistency.data?.items ?? []).slice(0, 12).map((row, idx) => (
                <tr key={`${row.id}-${idx}`} className="border-b border-[var(--border-default)]">
                  <td className="px-2 py-2 font-mono text-xs">{row.thread_id}</td>
                  <td className="px-2 py-2">{Number(row.consistency_score ?? 1).toFixed(2)}</td>
                  <td className="px-2 py-2">{String(row.conflicted_items ?? 0)}/{String(row.total_items ?? 0)}</td>
                  <td className="px-2 py-2">{row.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
