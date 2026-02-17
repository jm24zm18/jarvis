import { create } from "zustand";

export interface TraceEvent {
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

interface ChatStore {
  thinkingByThread: Record<string, boolean>;
  delegationByThread: Record<string, string>;
  activeTraceByThread: Record<string, string>;
  traceEvents: Record<string, TraceEvent[]>;
  setThinking: (threadId: string, value: boolean) => void;
  setDelegation: (threadId: string, chain: string) => void;
  setActiveTrace: (threadId: string, traceId: string) => void;
  setTraceEvents: (traceId: string, events: TraceEvent[]) => void;
  appendTraceEvent: (traceId: string, event: TraceEvent) => void;
  clearTrace: (threadId: string) => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  thinkingByThread: {},
  delegationByThread: {},
  activeTraceByThread: {},
  traceEvents: {},
  setThinking: (threadId, value) =>
    set((state) => ({ thinkingByThread: { ...state.thinkingByThread, [threadId]: value } })),
  setDelegation: (threadId, chain) =>
    set((state) => ({
      delegationByThread: { ...state.delegationByThread, [threadId]: chain },
    })),
  setActiveTrace: (threadId, traceId) =>
    set((state) => ({
      activeTraceByThread: { ...state.activeTraceByThread, [threadId]: traceId },
    })),
  setTraceEvents: (traceId, events) =>
    set((state) => ({
      traceEvents: {
        ...state.traceEvents,
        [traceId]: events,
      },
    })),
  appendTraceEvent: (traceId, event) =>
    set((state) => {
      const existing = state.traceEvents[traceId] ?? [];
      const duplicate = existing.some(
        (item) =>
          item.event_type === event.event_type &&
          item.created_at === event.created_at &&
          JSON.stringify(item.payload) === JSON.stringify(event.payload),
      );
      if (duplicate) return {};
      return {
        traceEvents: {
          ...state.traceEvents,
          [traceId]: [...existing, event],
        },
      };
    }),
  clearTrace: (threadId) =>
    set((state) => {
      const nextActive = { ...state.activeTraceByThread };
      const oldTraceId = nextActive[threadId];
      delete nextActive[threadId];
      const nextEvents = { ...state.traceEvents };
      if (oldTraceId) {
        delete nextEvents[oldTraceId];
      }
      return { activeTraceByThread: nextActive, traceEvents: nextEvents };
    }),
}));
