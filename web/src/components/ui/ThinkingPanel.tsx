import { X } from "lucide-react";
import type { TraceEvent } from "../../stores/chat";

interface Props {
  events: TraceEvent[];
  onClose: () => void;
}

function eventColor(eventType: string): string {
  if (eventType.includes("fallback")) return "border-amber-400 bg-amber-50 dark:bg-amber-900/20";
  if (eventType.includes("end") || eventType.includes("success"))
    return "border-emerald-400 bg-emerald-50 dark:bg-emerald-900/20";
  if (eventType.includes("error") || eventType.includes("fail"))
    return "border-red-400 bg-red-50 dark:bg-red-900/20";
  if (eventType.includes("delegated"))
    return "border-violet-400 bg-violet-50 dark:bg-violet-900/20";
  return "border-[var(--border-strong)] bg-surface";
}

function summarizeEvent(event: TraceEvent): string {
  const payload = event.payload;
  if (event.event_type === "model.run.start") {
    const iteration = Number(payload.iteration ?? 0);
    return `Thinking (iteration ${iteration + 1})`;
  }
  if (event.event_type === "model.run.end") {
    const lane = String(payload.lane ?? "unknown");
    return `Model responded (lane: ${lane})`;
  }
  if (event.event_type === "model.fallback") {
    return "Primary failed, switched to fallback model";
  }
  if (event.event_type === "tool.call.start") {
    return `Running tool: ${String(payload.tool ?? "unknown")}`;
  }
  if (event.event_type === "tool.call.end") {
    return `Tool finished: ${String(payload.tool ?? "unknown")}`;
  }
  if (event.event_type === "agent.delegated") {
    return `Delegating to ${String(payload.to_agent ?? "worker")}`;
  }
  return event.event_type;
}

export default function ThinkingPanel({ events, onClose }: Props) {
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
      <div className="max-h-[60vh] space-y-0 overflow-y-auto p-3">
        {events.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <div className="flex gap-1">
              <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] pulse-glow" />
              <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] pulse-glow [animation-delay:0.3s]" />
              <span className="h-2 w-2 rounded-full bg-[var(--text-muted)] pulse-glow [animation-delay:0.6s]" />
            </div>
            <p className="text-xs text-[var(--text-muted)]">Waiting for activity...</p>
          </div>
        ) : (
          events.map((event, index) => (
            <div key={`${event.created_at}-${index}`} className="relative flex gap-3 pb-3">
              {/* Timeline connector */}
              <div className="flex flex-col items-center">
                <div className="h-2.5 w-2.5 rounded-full border-2 border-[var(--text-muted)] bg-surface" />
                {index < events.length - 1 && (
                  <div className="w-px flex-1 bg-[var(--border-default)]" />
                )}
              </div>
              {/* Event card */}
              <div
                className={`flex-1 rounded-lg border px-3 py-2 ${eventColor(event.event_type)}`}
              >
                <div className="text-xs font-medium text-[var(--text-primary)]">
                  {summarizeEvent(event)}
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                  {new Date(event.created_at).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
