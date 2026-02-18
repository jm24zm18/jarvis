import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import type { TraceEvent } from "../../stores/chat";
import { formatThinkingEvent, getEventKey, truncateText } from "./thinkingFormat";

interface Props {
  events: TraceEvent[];
  onClose: () => void;
}

type FilterMode = "all" | "thoughts" | "tools" | "errors";

function statusClasses(status: string): string {
  if (status === "warning") return "border-amber-300 bg-amber-50 dark:bg-amber-900/20";
  if (status === "success") return "border-emerald-300 bg-emerald-50 dark:bg-emerald-900/20";
  if (status === "error") return "border-red-300 bg-red-50 dark:bg-red-900/20";
  return "border-[var(--border-strong)] bg-surface";
}

function statusDotClasses(status: string): string {
  if (status === "warning") return "bg-amber-500";
  if (status === "success") return "bg-emerald-500";
  if (status === "error") return "bg-red-500";
  return "bg-slate-500";
}

function matchesFilter(event: ReturnType<typeof formatThinkingEvent>, mode: FilterMode): boolean {
  if (mode === "all") return true;
  if (mode === "thoughts") return event.kind === "thought";
  if (mode === "tools") return event.kind === "tool_start" || event.kind === "tool_end";
  return event.status === "error";
}

function filterLabel(mode: FilterMode): string {
  if (mode === "thoughts") return "Thoughts";
  if (mode === "tools") return "Tools";
  if (mode === "errors") return "Errors";
  return "All";
}

export default function ThinkingPanel({ events, onClose }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const normalized = useMemo(
    () => events.map((event, index) => ({ key: getEventKey(event, index), raw: event, view: formatThinkingEvent(event) })),
    [events],
  );
  const visibleEvents = useMemo(
    () => normalized.filter((item) => matchesFilter(item.view, filterMode)),
    [filterMode, normalized],
  );

  return (
    <aside className="ml-3 w-80 shrink-0 overflow-hidden rounded-xl border border-[var(--border-default)] bg-surface shadow-lg transition-all">
      <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Agent Thinking</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-[var(--text-muted)] hover:bg-mist hover:text-[var(--text-primary)]"
        >
          <X size={16} />
        </button>
      </div>
      <div className="flex gap-1 border-b border-[var(--border-default)] px-3 py-2">
        {(["all", "thoughts", "tools", "errors"] as FilterMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => setFilterMode(mode)}
            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
              filterMode === mode
                ? "bg-[#13293d] text-white dark:bg-slate-200 dark:text-slate-900"
                : "bg-mist text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            }`}
          >
            {filterLabel(mode)}
          </button>
        ))}
      </div>
      <div className="max-h-[60vh] space-y-0 overflow-y-auto p-3">
        {visibleEvents.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <div className="flex gap-1">
              <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] pulse-glow" />
              <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] pulse-glow [animation-delay:0.3s]" />
              <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] pulse-glow [animation-delay:0.6s]" />
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              {events.length === 0 ? "Waiting for activity..." : "No events for this filter."}
            </p>
          </div>
        ) : (
          visibleEvents.map((item, index) => (
            <div key={item.key} className="relative flex gap-3 pb-3">
              {/* Timeline connector */}
              <div className="flex flex-col items-center">
                <div className={`h-2.5 w-2.5 rounded-full ${statusDotClasses(item.view.status)}`} />
                {index < visibleEvents.length - 1 && (
                  <div className="w-px flex-1 bg-[var(--border-default)]" />
                )}
              </div>
              {/* Event card */}
              <div
                className={`flex-1 rounded-lg border px-2.5 py-2 ${statusClasses(item.view.status)}`}
              >
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((state) => ({ ...state, [item.key]: !state[item.key] }))
                  }
                  className="flex w-full items-start gap-1 text-left"
                >
                  <div className="pt-0.5 text-[var(--text-muted)]">
                    {expanded[item.key] ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <div className="truncate text-xs font-medium text-[var(--text-primary)]">
                        {item.view.title}
                      </div>
                      <span className="rounded border border-[var(--border-default)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-muted)]">
                        {item.view.eventType}
                      </span>
                    </div>
                    <div className="text-[10px] text-[var(--text-muted)]">
                      {new Date(item.raw.created_at).toLocaleTimeString()}
                    </div>
                  </div>
                </button>
                {item.view.preview ? (
                  <div className="mt-1 whitespace-pre-wrap break-words pl-5 text-[11px] text-[var(--text-primary)]">
                    {truncateText(item.view.preview, 220)}
                  </div>
                ) : null}
                {expanded[item.key] ? (
                  <div className="mt-2 space-y-2 border-t border-[var(--border-default)] pt-2 pl-5">
                    {item.view.details
                      .filter((section: { label: string; value: string; raw?: boolean }) => !section.raw)
                      .map((section: { label: string; value: string; code?: boolean; emphasis?: string }) => (
                        <section key={section.label}>
                          <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                            {section.label}
                          </div>
                          <pre
                            className={`mt-0.5 whitespace-pre-wrap break-words text-[11px] ${
                              section.code ? "font-mono" : ""
                            } ${section.emphasis === "error" ? "text-red-700 dark:text-red-300" : "text-[var(--text-primary)]"}`}
                          >
                            {section.value}
                          </pre>
                        </section>
                      ))}
                    <details>
                      <summary className="cursor-pointer text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                        Raw payload
                      </summary>
                      <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] text-[var(--text-primary)]">
                        {item.view.details.find((section: { raw?: boolean }) => section.raw)?.value ?? "{}"}
                      </pre>
                    </details>
                  </div>
                ) : null}
                <div className="mt-0.5 text-[11px] text-[var(--text-muted)] sr-only">
                  {new Date(item.raw.created_at).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
