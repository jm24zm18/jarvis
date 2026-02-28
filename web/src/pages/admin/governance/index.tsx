import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  dependencyStewardStatus,
  fitnessHistory,
  governanceDecisionTimeline,
  governanceEvolutionItems,
  governanceLearningLoop,
  governancePatchLifecycle,
  governanceRemediationFeedback,
  governanceSlo,
  governanceSloHistory,
  latestFitness,
  memoryConsistencyReport,
  releaseCandidateStatus,
} from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";
import { formatPercent, formatTimestampHuman } from "../../../lib/format";

function asNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function toIsoOrUndefined(value: string): string | undefined {
  if (!value.trim()) return undefined;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return parsed.toISOString();
}

export default function AdminGovernancePage() {
  const queryClient = useQueryClient();
  const [evolutionStatus, setEvolutionStatus] = useState("");
  const [evolutionTraceId, setEvolutionTraceId] = useState("");
  const [evolutionFrom, setEvolutionFrom] = useState("");
  const [evolutionTo, setEvolutionTo] = useState("");

  const fitness = useQuery({ queryKey: ["governance-fitness-latest"], queryFn: latestFitness });
  const history = useQuery({ queryKey: ["governance-fitness-history"], queryFn: () => fitnessHistory(8) });
  const slo = useQuery({ queryKey: ["governance-slo"], queryFn: governanceSlo });
  const sloHistory = useQuery({ queryKey: ["governance-slo-history"], queryFn: () => governanceSloHistory(12) });
  const dependency = useQuery({ queryKey: ["governance-dependency"], queryFn: dependencyStewardStatus });
  const release = useQuery({ queryKey: ["governance-release"], queryFn: releaseCandidateStatus });
  const timeline = useQuery({
    queryKey: ["governance-decision-timeline"],
    queryFn: () => governanceDecisionTimeline({ limit: 25 }),
  });
  const evolutionItems = useQuery({
    queryKey: ["governance-evolution-items", evolutionStatus, evolutionTraceId, evolutionFrom, evolutionTo],
    queryFn: () =>
      governanceEvolutionItems({
        status: evolutionStatus || undefined,
        trace_id: evolutionTraceId || undefined,
        from: toIsoOrUndefined(evolutionFrom),
        to: toIsoOrUndefined(evolutionTo),
        limit: 25,
      }),
  });
  const memoryConsistency = useQuery({
    queryKey: ["governance-memory-consistency"],
    queryFn: () => memoryConsistencyReport({ limit: 20 }),
  });
  const learning = useQuery({
    queryKey: ["governance-learning-loop"],
    queryFn: () => governanceLearningLoop(14, true),
  });
  const feedback = useMutation({
    mutationFn: ({ remediationId, value }: { remediationId: string; value: "accepted" | "rejected" }) =>
      governanceRemediationFeedback(remediationId, value),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["governance-learning-loop"] });
    },
  });

  const timelineItems = ((timeline.data?.items as Array<Record<string, unknown>> | undefined) ?? []);
  const latestTraceId = typeof timelineItems[0]?.trace_id === "string" ? String(timelineItems[0]?.trace_id) : "";
  const lifecycle = useQuery({
    queryKey: ["governance-patch-lifecycle", latestTraceId],
    queryFn: () => governancePatchLifecycle(latestTraceId),
    enabled: !!latestTraceId,
  });

  const latest = fitness.data?.item;
  const metrics = latest?.metrics ?? {};
  const storyPassRate = asNumber(metrics.story_pack_pass_rate);
  const selfupdateSuccessRate = asNumber(metrics.selfupdate_success_rate);
  const recurrenceRate = asNumber(metrics.failure_capsule_recurrence_rate);

  const releaseStatus = String(release.data?.status ?? "unknown");
  const blockers = Array.isArray(release.data?.blockers) ? release.data?.blockers : [];
  const proposals = Array.isArray(dependency.data?.proposals) ? dependency.data?.proposals : [];
  const traceHref = (traceId: string, itemThreadId?: string) => {
    const query = new URLSearchParams({ trace_id: traceId });
    if (itemThreadId) query.set("thread_id", itemThreadId);
    return `/admin/events?${query.toString()}`;
  };

  return (
    <div>
      <Header title="Governance" subtitle="System fitness, release readiness, and dependency stewardship" />
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant={
              slo.data?.status === "safe" ? "success" : slo.data?.status === "blocked" ? "danger" : "warning"
            }
          >
            SLO {String(slo.data?.status ?? "unknown")}
          </Badge>
          {Array.isArray(slo.data?.reasons) && slo.data?.reasons.length > 0 ? (
            <span className="text-xs text-text2">{slo.data?.reasons.join(" | ")}</span>
          ) : (
            <span className="text-xs text-text3">No active SLO degradation reasons.</span>
          )}
        </div>
      </Card>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <p className="text-xs uppercase tracking-wide text-text3">Story Pass Rate</p>
          <p className="mt-2 font-mono text-3xl text-text">{formatPercent(storyPassRate * 100, 2)}</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-text3">Self-Update Success</p>
          <p className="mt-2 font-mono text-3xl text-text">{formatPercent(selfupdateSuccessRate * 100, 2)}</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-text3">Failure Recurrence</p>
          <p className="mt-2 font-mono text-3xl text-text">{formatPercent(recurrenceRate * 100, 2)}</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-text3">Memory Consistency</p>
          <p className="mt-2 font-mono text-3xl text-text">
            {formatPercent(Number(memoryConsistency.data?.avg_consistency ?? 1) * 100, 2)}
          </p>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          header={
            <div className="flex items-center justify-between">
              <h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Release Candidate</h3>
              <Badge variant={releaseStatus === "ready" ? "success" : "warning"}>{releaseStatus}</Badge>
            </div>
          }
        >
          {blockers.length === 0 ? (
            <p className="text-sm text-text3">No blockers reported.</p>
          ) : (
            <ul className="space-y-2 text-sm text-text2">
              {blockers.map((item) => (
                <li key={String(item)}>{String(item)}</li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          header={
            <div className="flex items-center justify-between">
              <h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Dependency Steward</h3>
              <Badge variant="info">{proposals.length} proposals</Badge>
            </div>
          }
        >
          {proposals.length === 0 ? (
            <p className="text-sm text-text3">No upgrade proposals available.</p>
          ) : (
            <ul className="space-y-2 text-sm text-text2">
              {proposals.slice(0, 10).map((item, idx) => {
                const proposal = item as Record<string, unknown>;
                return (
                  <li key={`${proposal.package ?? "pkg"}-${idx}`}>
                    {String(proposal.package ?? "package")} {String(proposal.from_version ?? "")}
                    {" -> "}
                    {String(proposal.to_version ?? "")}
                    {" ("}
                    {String(proposal.risk ?? "unknown")}
                    {")"}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-6" header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Fitness History</h3>}>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-[10px] font-mono uppercase tracking-widest text-text3 font-medium">
                <th className="px-2 py-2">Created</th>
                <th className="px-2 py-2">Window</th>
                <th className="px-2 py-2">Story</th>
                <th className="px-2 py-2">Self-Update</th>
              </tr>
            </thead>
            <tbody>
              {(history.data?.items ?? []).map((item) => {
                const rowMetrics = item.metrics ?? {};
                return (
                  <tr key={item.id} className="border-b border-[var(--color-border)]">
                    <td className="px-2 py-2">{formatTimestampHuman(item.created_at)}</td>
                    <td className="px-2 py-2">
                      {formatTimestampHuman(item.period_start)} .. {formatTimestampHuman(item.period_end)}
                    </td>
                    <td className="px-2 py-2">{formatPercent(asNumber(rowMetrics.story_pack_pass_rate) * 100, 2)}</td>
                    <td className="px-2 py-2">{formatPercent(asNumber(rowMetrics.selfupdate_success_rate) * 100, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mt-6" header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">SLO History</h3>}>
        <ul className="space-y-2 text-sm text-text2">
          {(sloHistory.data?.items ?? []).slice(0, 10).map((item) => (
            <li key={item.snapshot_id}>
              {formatTimestampHuman(item.created_at)} • {item.status}
              {item.reasons.length > 0 ? ` • ${item.reasons.join(", ")}` : ""}
            </li>
          ))}
        </ul>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Decision Timeline</h3>}>
          <ul className="space-y-2 text-sm text-text2">
            {timelineItems.slice(0, 8).map((item, idx) => (
              <li key={`${String(item.id ?? "evt")}-${idx}`}>
                <div className="flex items-center justify-between gap-2">
                  <span>
                    {formatTimestampHuman(String(item.created_at ?? ""))} • {String(item.event_type ?? "")}
                  </span>
                  {typeof item.trace_id === "string" && item.trace_id ? (
                    <Link
                      className="rounded border border-[var(--color-border)] px-2 py-0.5 text-xs hover:bg-surface-2"
                      to={traceHref(item.trace_id, typeof item.thread_id === "string" ? item.thread_id : undefined)}
                    >
                      Open Trace
                    </Link>
                  ) : null}
                </div>
              </li>
            ))}
            {timelineItems.length === 0 ? (
              <li>No decision timeline events found.</li>
            ) : null}
          </ul>
        </Card>

        <Card header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Learning Loop</h3>}>
          <ul className="space-y-2 text-sm text-text2">
            {((learning.data?.items as Array<Record<string, unknown>> | undefined) ?? []).slice(0, 8).map((item, idx) => {
              const remediations = Array.isArray(item.remediations)
                ? (item.remediations as Array<Record<string, unknown>>)
                : [];
              return (
                <li key={`${String(item.id ?? "pat")}-${idx}`}>
                  <div>
                    {String(item.phase ?? "")}: {String(item.latest_reason ?? "")} ({String(item.count ?? 0)})
                  </div>
                  {remediations.slice(0, 1).map((remediation) => (
                    <div key={String(remediation.id ?? "rem")} className="mt-1 flex items-center gap-2 text-xs">
                      <span className="text-text3">{String(remediation.remediation ?? "")}</span>
                      <button
                        className="rounded border border-[var(--color-border)] px-1.5 py-0.5 hover:bg-surface-2"
                        onClick={() =>
                          feedback.mutate({ remediationId: String(remediation.id), value: "accepted" })
                        }
                      >
                        Accept
                      </button>
                      <button
                        className="rounded border border-[var(--color-border)] px-1.5 py-0.5 hover:bg-surface-2"
                        onClick={() =>
                          feedback.mutate({ remediationId: String(remediation.id), value: "rejected" })
                        }
                      >
                        Reject
                      </button>
                    </div>
                  ))}
                </li>
              );
            })}
            {((learning.data?.items as Array<Record<string, unknown>> | undefined) ?? []).length === 0 ? (
              <li>No learning patterns available.</li>
            ) : null}
          </ul>
        </Card>
      </div>

      <Card className="mt-6" header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Evolution Items</h3>}>
        <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-4">
          <select
            className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm outline-none focus:border-accent"
            value={evolutionStatus}
            onChange={(event) => setEvolutionStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="started">started</option>
            <option value="verified">verified</option>
            <option value="blocked">blocked</option>
          </select>
          <input
            className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm outline-none focus:border-accent placeholder:text-text3"
            placeholder="Filter trace_id"
            value={evolutionTraceId}
            onChange={(event) => setEvolutionTraceId(event.target.value)}
          />
          <input
            className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm outline-none focus:border-accent text-text"
            type="datetime-local"
            value={evolutionFrom}
            onChange={(event) => setEvolutionFrom(event.target.value)}
          />
          <input
            className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm outline-none focus:border-accent text-text"
            type="datetime-local"
            value={evolutionTo}
            onChange={(event) => setEvolutionTo(event.target.value)}
          />
        </div>
        {evolutionItems.isLoading ? (
          <p className="text-sm text-text3">Loading evolution items...</p>
        ) : (evolutionItems.data?.items ?? []).length === 0 ? (
          <p className="text-sm text-text3">No evolution items found.</p>
        ) : (
          <ul className="space-y-2 text-sm text-text2">
            {(evolutionItems.data?.items ?? []).map((item) => (
              <li key={item.item_id} className="flex items-center justify-between gap-2">
                <span>
                  {item.item_id} • {item.status} • {formatTimestampHuman(item.updated_at)}
                </span>
                <Link
                  className="rounded border border-[var(--color-border)] px-2 py-0.5 text-xs hover:bg-surface-2"
                  to={traceHref(item.trace_id, item.thread_id ?? undefined)}
                >
                  Open Trace
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="mt-6" header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Patch Lifecycle</h3>}>
        {latestTraceId ? (
          <div className="mb-2">
            <Link
              className="rounded border border-[var(--color-border)] px-2 py-1 text-xs hover:bg-surface-2"
              to={traceHref(latestTraceId)}
            >
              Open Latest Trace In Events
            </Link>
          </div>
        ) : null}
        <pre className="overflow-auto rounded bg-surface-2 p-3 text-xs text-text2">
          {JSON.stringify(lifecycle.data ?? { status: "no-trace-context" }, null, 2)}
        </pre>
      </Card>
    </div>
  );
}
