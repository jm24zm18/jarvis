import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { RefreshCw, CheckCircle, Clock, AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import {
  approvePatch,
  getPatch,
  governanceSlo,
  listPatches,
  patchChecks,
  patchTimeline,
} from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Card from "../../../components/ui/Card";
import DiffViewer from "../../../components/ui/DiffViewer";
import Pagination from "../../../components/ui/Pagination";

const PAGE_SIZE = 12;

function patchStateVariant(state: string): "success" | "warning" | "danger" | "info" | "default" {
  switch (state) {
    case "approved":
      return "success";
    case "tested":
      return "info";
    case "pending":
      return "warning";
    case "failed":
    case "rejected":
      return "danger";
    default:
      return "default";
  }
}

function patchStateIcon(state: string) {
  switch (state) {
    case "approved":
      return <CheckCircle className="h-3.5 w-3.5" />;
    case "tested":
      return <RefreshCw className="h-3.5 w-3.5" />;
    case "pending":
      return <Clock className="h-3.5 w-3.5" />;
    case "failed":
    case "rejected":
      return <AlertTriangle className="h-3.5 w-3.5" />;
    default:
      return <Clock className="h-3.5 w-3.5" />;
  }
}

export default function AdminSelfUpdatePage() {
  const [selectedTraceId, setSelectedTraceId] = useState("");
  const [page, setPage] = useState(1);
  const patches = useQuery({ queryKey: ["patches"], queryFn: listPatches });
  const slo = useQuery({ queryKey: ["governance-slo"], queryFn: governanceSlo });
  const detail = useQuery({
    queryKey: ["patch", selectedTraceId],
    queryFn: () => getPatch(selectedTraceId),
    enabled: !!selectedTraceId,
  });
  const checks = useQuery({
    queryKey: ["patch-checks", selectedTraceId],
    queryFn: () => patchChecks(selectedTraceId),
    enabled: !!selectedTraceId,
  });
  const timeline = useQuery({
    queryKey: ["patch-timeline", selectedTraceId],
    queryFn: () => patchTimeline(selectedTraceId),
    enabled: !!selectedTraceId,
  });
  const approve = useMutation({
    mutationFn: (traceId: string) => approvePatch(traceId),
    onSuccess: () => {
      void patches.refetch();
      void detail.refetch();
    },
  });

  const allPatches = patches.data?.items ?? [];
  const pagedPatches = allPatches.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div>
      <Header
        title="Self-Update"
        subtitle="Review proposed and tested patches, then issue approval"
        icon={<RefreshCw className="h-6 w-6" />}
      />
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant={
              slo.data?.status === "safe" ? "success" : slo.data?.status === "blocked" ? "danger" : "warning"
            }
          >
            SLO {String(slo.data?.status ?? "unknown")}
          </Badge>
          <span className="text-xs text-[var(--text-secondary)]">
            {Array.isArray(slo.data?.reasons) && slo.data?.reasons.length > 0
              ? slo.data?.reasons.join(" | ")
              : "No active SLO degradation reasons."}
          </span>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        {/* Patch List Sidebar */}
        <Card
          header={
            <div className="flex items-center justify-between">
              <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                Patches
              </span>
              <Badge variant="info">{allPatches.length} total</Badge>
            </div>
          }
          footer={
            <Pagination page={page} pageSize={PAGE_SIZE} total={allPatches.length} onPage={setPage} />
          }
        >
          <div className="space-y-2">
            {pagedPatches.length === 0 && (
              <p className="py-8 text-center text-sm text-[var(--text-muted)]">
                No patches found.
              </p>
            )}
            {pagedPatches.map((patch) => (
              <button
                key={patch.trace_id}
                onClick={() => setSelectedTraceId(patch.trace_id)}
                className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                  selectedTraceId === patch.trace_id
                    ? "border-ember/40 bg-ember/5"
                    : "border-[var(--border-default)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-mist)]"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    {patchStateIcon(patch.state)}
                    <Badge variant={patchStateVariant(patch.state)}>{patch.state}</Badge>
                  </div>
                </div>
                <p className="mt-1.5 truncate text-xs text-[var(--text-muted)]">
                  {patch.trace_id}
                </p>
                {patch.detail && (
                  <p className="mt-1 line-clamp-2 text-xs text-[var(--text-secondary)]">
                    {patch.detail}
                  </p>
                )}
              </button>
            ))}
          </div>
        </Card>

        {/* Patch Detail + Diff */}
        <Card
          header={
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-[var(--text-muted)]" />
                <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
                  Patch Detail
                </span>
              </div>
              {detail.data && (
                <Badge variant={patchStateVariant(detail.data.state)}>
                  {detail.data.state}
                </Badge>
              )}
            </div>
          }
        >
          {!selectedTraceId ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <RefreshCw className="mb-3 h-10 w-10 text-[var(--text-muted)]" />
              <p className="text-sm text-[var(--text-muted)]">
                Select a patch from the list to review
              </p>
            </div>
          ) : detail.isLoading ? (
            <p className="py-12 text-center text-sm text-[var(--text-muted)]">Loading patch...</p>
          ) : detail.data ? (
            <div className="space-y-4">
              {/* Patch Meta */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-3 py-1.5">
                  <span className="text-xs text-[var(--text-muted)]">Trace ID</span>
                  <p className="text-sm font-medium text-[var(--text-primary)]">
                    {detail.data.trace_id}
                  </p>
                </div>
                <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-3 py-1.5">
                  <span className="text-xs text-[var(--text-muted)]">State</span>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    {patchStateIcon(detail.data.state)}
                    <span className="text-sm font-medium text-[var(--text-primary)]">
                      {detail.data.state}
                    </span>
                  </div>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<CheckCircle className="h-3.5 w-3.5" />}
                  onClick={() => approve.mutate(detail.data.trace_id)}
                  disabled={approve.isPending || detail.data.state !== "tested"}
                >
                  {approve.isPending ? "Approving..." : "Approve Tested Patch"}
                </Button>
                <Link
                  className="rounded-lg border border-[var(--border-default)] px-2.5 py-1 text-xs hover:bg-[var(--bg-mist)]"
                  to={`/admin/events?trace_id=${encodeURIComponent(detail.data.trace_id)}`}
                >
                  View In Events
                </Link>
                <Badge variant="default">
                  {timeline.data?.transitions?.length ?? 0} transitions
                </Badge>
                <Badge variant="default">{checks.data?.items?.length ?? 0} checks</Badge>
              </div>

              {detail.data.detail && (
                <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-3 py-2">
                  <span className="text-xs text-[var(--text-muted)]">Detail</span>
                  <p className="mt-0.5 text-sm text-[var(--text-primary)]">{detail.data.detail}</p>
                </div>
              )}

              {/* Diff Viewer */}
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Diff
                </h4>
                <DiffViewer diff={detail.data.diff} />
              </div>
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
