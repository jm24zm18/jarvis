import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import type { TraceEvent } from "../../stores/chat";
import { formatThinkingEvent, getEventKey, truncateText } from "./thinkingFormat";
import { formatTimeHuman } from "../../lib/format";

interface Props {
  events: TraceEvent[];
  onClose: () => void;
}

type FilterMode = "all" | "thoughts" | "tools" | "errors";

function statusClasses(status: string): string {
  if (status === "warning") return "border-warning/30 bg-warning-dim";
  if (status === "success") return "border-success/30 bg-success-dim";
  if (status === "error") return "border-danger/30 bg-danger-dim";
  return "border-[var(--color-border)] bg-[var(--color-surface-2)]";
}

function statusDotClasses(status: string): string {
  if (status === "warning") return "bg-warning";
  if (status === "success") return "bg-success";
  if (status === "error") return "bg-danger";
  return "bg-text4";
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
    <aside className="ml-3 w-80 shrink-0 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] transition-all">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
        <h3 className="font-mono text-[10px] font-semibold uppercase tracking-widest text-text3">
          // thinking
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-text3 hover:bg-surface-2 hover:text-text"
        >
          <X size={15} />
        </button>
      </div>
      <div className="flex gap-1 border-b border-[var(--color-border)] px-3 py-2">
        {(["all", "thoughts", "tools", "errors"] as FilterMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => setFilterMode(mode)}
            className={`rounded-full px-2 py-0.5 font-mono text-[10px] font-medium transition-colors ${
              filterMode === mode
                ? "bg-accent text-zinc-950"
                : "bg-surface-2 text-text3 hover:text-text"
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
              <span className="h-2 w-2 rounded-full bg-text4 pulse-glow" />
              <span className="h-2 w-2 rounded-full bg-text4 pulse-glow [animation-delay:0.3s]" />
              <span className="h-2 w-2 rounded-full bg-text4 pulse-glow [animation-delay:0.6s]" />
            </div>
            <p className="font-mono text-[10px] text-text3">
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
                  <div className="w-px flex-1 bg-[var(--color-border)]" />
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
                  <div className="pt-0.5 text-text3">
                    {expanded[item.key] ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <div className="truncate font-mono text-xs font-medium text-text">
                        {item.view.title}
                      </div>
                      <span className="rounded border border-[var(--color-border)] px-1 py-0.5 font-mono text-[10px] text-text3">
                        {item.view.eventType}
                      </span>
                    </div>
                    <div className="font-mono text-[10px] text-text4 [font-variant-numeric:tabular-nums]">
                      {formatTimeHuman(item.raw.created_at)}
                    </div>
                  </div>
                </button>
                {item.view.preview ? (
                  <div className="mt-1 whitespace-pre-wrap break-words pl-5 font-mono text-[11px] text-text2">
                    {truncateText(item.view.preview, 220)}
                  </div>
                ) : null}
                {expanded[item.key] ? (
                  <div className="mt-2 space-y-2 border-t border-[var(--color-border)] pt-2 pl-5">
                    {item.view.details
                      .filter((section: { label: string; value: string; raw?: boolean }) => !section.raw)
                      .map((section: { label: string; value: string; code?: boolean; emphasis?: string }) => (
                        <section key={section.label}>
                          <div className="font-mono text-[10px] uppercase tracking-widest text-text3">
                            {section.label}
                          </div>
                          <pre
                            className={`mt-0.5 whitespace-pre-wrap break-words text-[11px] ${
                              section.code ? "font-mono" : ""
                            } ${section.emphasis === "error" ? "text-danger" : "text-text2"}`}
                          >
                            {section.value}
                          </pre>
                        </section>
                      ))}
                    <details>
                      <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-widest text-text3">
                        Raw payload
                      </summary>
                      <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] text-text2">
                        {item.view.details.find((section: { raw?: boolean }) => section.raw)?.value ?? "{}"}
                      </pre>
                    </details>
                  </div>
                ) : null}
                <div className="sr-only mt-0.5 font-mono text-[11px] text-text4 [font-variant-numeric:tabular-nums]">
                  {formatTimeHuman(item.raw.created_at)}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
