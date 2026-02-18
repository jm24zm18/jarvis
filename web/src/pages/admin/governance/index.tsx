import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dependencyStewardStatus,
  fitnessHistory,
  governanceDecisionTimeline,
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

function asNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export default function AdminGovernancePage() {
  const queryClient = useQueryClient();
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
            <span className="text-xs text-[var(--text-secondary)]">{slo.data?.reasons.join(" | ")}</span>
          ) : (
            <span className="text-xs text-[var(--text-muted)]">No active SLO degradation reasons.</span>
          )}
        </div>
      </Card>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Story Pass Rate</p>
          <p className="mt-2 font-display text-3xl text-[var(--text-primary)]">{(storyPassRate * 100).toFixed(1)}%</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Self-Update Success</p>
          <p className="mt-2 font-display text-3xl text-[var(--text-primary)]">{(selfupdateSuccessRate * 100).toFixed(1)}%</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Failure Recurrence</p>
          <p className="mt-2 font-display text-3xl text-[var(--text-primary)]">{(recurrenceRate * 100).toFixed(1)}%</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Memory Consistency</p>
          <p className="mt-2 font-display text-3xl text-[var(--text-primary)]">
            {(Number(memoryConsistency.data?.avg_consistency ?? 1) * 100).toFixed(1)}%
          </p>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          header={
            <div className="flex items-center justify-between">
              <h3 className="font-display text-base text-[var(--text-primary)]">Release Candidate</h3>
              <Badge variant={releaseStatus === "ready" ? "success" : "warning"}>{releaseStatus}</Badge>
            </div>
          }
        >
          {blockers.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No blockers reported.</p>
          ) : (
            <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
              {blockers.map((item) => (
                <li key={String(item)}>{String(item)}</li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          header={
            <div className="flex items-center justify-between">
              <h3 className="font-display text-base text-[var(--text-primary)]">Dependency Steward</h3>
              <Badge variant="info">{proposals.length} proposals</Badge>
            </div>
          }
        >
          {proposals.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No upgrade proposals available.</p>
          ) : (
            <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
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

      <Card className="mt-6" header={<h3 className="font-display text-base text-[var(--text-primary)]">Fitness History</h3>}>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-default)] text-left text-xs uppercase tracking-wide text-[var(--text-muted)]">
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
                  <tr key={item.id} className="border-b border-[var(--border-default)]">
                    <td className="px-2 py-2">{item.created_at}</td>
                    <td className="px-2 py-2">{item.period_start} .. {item.period_end}</td>
                    <td className="px-2 py-2">{(asNumber(rowMetrics.story_pack_pass_rate) * 100).toFixed(1)}%</td>
                    <td className="px-2 py-2">{(asNumber(rowMetrics.selfupdate_success_rate) * 100).toFixed(1)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mt-6" header={<h3 className="font-display text-base text-[var(--text-primary)]">SLO History</h3>}>
        <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
          {(sloHistory.data?.items ?? []).slice(0, 10).map((item) => (
            <li key={item.snapshot_id}>
              {item.created_at} • {item.status}
              {item.reasons.length > 0 ? ` • ${item.reasons.join(", ")}` : ""}
            </li>
          ))}
        </ul>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card header={<h3 className="font-display text-base text-[var(--text-primary)]">Decision Timeline</h3>}>
          <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
            {timelineItems.slice(0, 8).map((item, idx) => (
              <li key={`${String(item.id ?? "evt")}-${idx}`}>
                {String(item.created_at ?? "")} • {String(item.event_type ?? "")}
              </li>
            ))}
            {timelineItems.length === 0 ? (
              <li>No decision timeline events found.</li>
            ) : null}
          </ul>
        </Card>

        <Card header={<h3 className="font-display text-base text-[var(--text-primary)]">Learning Loop</h3>}>
          <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
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
                      <span className="text-[var(--text-muted)]">{String(remediation.remediation ?? "")}</span>
                      <button
                        className="rounded border border-[var(--border-default)] px-1.5 py-0.5 hover:bg-[var(--bg-mist)]"
                        onClick={() =>
                          feedback.mutate({ remediationId: String(remediation.id), value: "accepted" })
                        }
                      >
                        Accept
                      </button>
                      <button
                        className="rounded border border-[var(--border-default)] px-1.5 py-0.5 hover:bg-[var(--bg-mist)]"
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

      <Card className="mt-6" header={<h3 className="font-display text-base text-[var(--text-primary)]">Patch Lifecycle</h3>}>
        <pre className="overflow-auto rounded bg-[var(--bg-mist)] p-3 text-xs text-[var(--text-secondary)]">
          {JSON.stringify(lifecycle.data ?? { status: "no-trace-context" }, null, 2)}
        </pre>
      </Card>
    </div>
  );
}
