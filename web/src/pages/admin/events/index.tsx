import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Search } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { getTrace, listEvents } from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Pagination from "../../../components/ui/Pagination";
import TraceTree from "../../../components/ui/TraceTree";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";

const PAGE_SIZE = 20;

export default function AdminEventsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [eventType, setEventType] = useState(() => searchParams.get("event_type") ?? "");
  const [component, setComponent] = useState(() => searchParams.get("component") ?? "");
  const [threadId, setThreadId] = useState(() => searchParams.get("thread_id") ?? "");
  const [query, setQuery] = useState(() => searchParams.get("query") ?? "");
  const [selectedTrace, setSelectedTrace] = useState(() => searchParams.get("trace_id") ?? "");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const nextEventType = searchParams.get("event_type") ?? "";
    const nextComponent = searchParams.get("component") ?? "";
    const nextThreadId = searchParams.get("thread_id") ?? "";
    const nextQuery = searchParams.get("query") ?? "";
    const nextTrace = searchParams.get("trace_id") ?? "";
    if (nextEventType !== eventType) setEventType(nextEventType);
    if (nextComponent !== component) setComponent(nextComponent);
    if (nextThreadId !== threadId) setThreadId(nextThreadId);
    if (nextQuery !== query) setQuery(nextQuery);
    if (nextTrace !== selectedTrace) setSelectedTrace(nextTrace);
  }, [component, eventType, query, searchParams, selectedTrace, threadId]);

  const writeSearchParams = (next: {
    event_type?: string;
    component?: string;
    thread_id?: string;
    query?: string;
    trace_id?: string;
  }) => {
    const out = new URLSearchParams();
    if (next.event_type) out.set("event_type", next.event_type);
    if (next.component) out.set("component", next.component);
    if (next.thread_id) out.set("thread_id", next.thread_id);
    if (next.query) out.set("query", next.query);
    if (next.trace_id) out.set("trace_id", next.trace_id);
    setSearchParams(out);
  };

  const filters = useMemo(
    () => ({ event_type: eventType, component, thread_id: threadId, query }),
    [component, eventType, query, threadId],
  );

  const events = useQuery({ queryKey: ["events", filters], queryFn: () => listEvents(filters) });
  const trace = useQuery({
    queryKey: ["trace", selectedTrace],
    queryFn: () => getTrace(selectedTrace),
    enabled: !!selectedTrace,
  });

  const allItems = events.data?.items ?? [];
  const paged = allItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div>
      <Header title="Events" subtitle="Filter by type/component/thread and inspect traces" />

      {/* Search filters */}
      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Input
            label="Event Type"
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
            placeholder="e.g. tool.call"
          />
          <Input
            label="Component"
            value={component}
            onChange={(e) => setComponent(e.target.value)}
            placeholder="e.g. planner"
          />
          <Input
            label="Thread ID"
            value={threadId}
            onChange={(e) => setThreadId(e.target.value)}
            placeholder="thread_id"
          />
          <Input
            label="Query Text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="full-text search"
          />
          <div className="flex items-end">
            <Button
              icon={<Search className="h-4 w-4" />}
              className="w-full"
              onClick={() => {
                setPage(1);
                writeSearchParams({
                  event_type: eventType,
                  component,
                  thread_id: threadId,
                  query,
                  trace_id: selectedTrace,
                });
                void events.refetch();
              }}
            >
              Search
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_1fr]">
        {/* Events table */}
        <Card
          header={
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-[var(--text-muted)]" />
                <h3 className="font-display text-base text-[var(--text-primary)]">Events</h3>
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
                    Created
                  </th>
                  <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                    Type
                  </th>
                  <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                    Component
                  </th>
                  <th className="px-4 py-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                    Trace
                  </th>
                </tr>
              </thead>
              <tbody>
                {paged.map((item) => {
                  const isSelected = item.trace_id === selectedTrace;
                  return (
                    <tr
                      key={item.id}
                      className={`cursor-pointer border-b border-[var(--border-default)] transition ${
                        isSelected
                          ? "bg-blue-50 dark:bg-blue-900/20"
                          : "hover:bg-[var(--bg-mist)]"
                      }`}
                      onClick={() => {
                        const traceId = item.trace_id ?? "";
                        setSelectedTrace(traceId);
                        writeSearchParams({
                          event_type: eventType,
                          component,
                          thread_id: threadId,
                          query,
                          trace_id: traceId,
                        });
                      }}
                    >
                      <td className="whitespace-nowrap px-4 py-2.5 text-xs text-[var(--text-muted)]">
                        {item.created_at}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge variant="info">{item.event_type}</Badge>
                      </td>
                      <td className="px-4 py-2.5 text-sm text-[var(--text-secondary)]">
                        {item.component}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-[var(--text-muted)]">
                        {item.trace_id ? item.trace_id.slice(0, 12) + "..." : "-"}
                      </td>
                    </tr>
                  );
                })}
                {paged.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">
                      No events found. Adjust your filters and search again.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Trace viewer */}
        <Card
          header={
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-[var(--text-muted)]" />
              <h3 className="font-display text-base text-[var(--text-primary)]">Trace Viewer</h3>
              {selectedTrace ? (
                <Badge variant="info" className="ml-auto">
                  {selectedTrace.slice(0, 12)}...
                </Badge>
              ) : null}
            </div>
          }
        >
          {!selectedTrace ? (
            <div className="flex min-h-[200px] items-center justify-center">
              <p className="text-sm text-[var(--text-muted)]">
                Click an event row to load its trace.
              </p>
            </div>
          ) : trace.isLoading ? (
            <div className="flex min-h-[200px] items-center justify-center">
              <p className="text-sm text-[var(--text-muted)]">Loading trace...</p>
            </div>
          ) : (
            <TraceTree events={trace.data?.items ?? []} />
          )}
        </Card>
      </div>
    </div>
  );
}
