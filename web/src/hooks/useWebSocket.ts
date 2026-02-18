import { useCallback, useEffect, useMemo, useRef } from "react";
import { useAuthStore } from "../stores/auth";

const MAX_BACKOFF = 30_000;

export function useWebSocket(onEvent: (payload: Record<string, unknown>) => void) {
  const socketRef = useRef<WebSocket | null>(null);
  const queueRef = useRef<string[]>([]);
  const subscribedRef = useRef<Set<string>>(new Set());
  const systemSubRef = useRef(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const backoffRef = useRef(1000);
  const reconnectTimerRef = useRef<number | null>(null);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    if (!isAuthenticated) {
      socketRef.current?.close();
      socketRef.current = null;
      queueRef.current = [];
      return;
    }

    let disposed = false;

    function connect() {
      if (disposed) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
      socketRef.current = ws;

      ws.onopen = () => {
        backoffRef.current = 1000;
        // Re-subscribe to all tracked threads
        for (const threadId of subscribedRef.current) {
          ws.send(JSON.stringify({ action: "subscribe", thread_id: threadId }));
        }
        if (systemSubRef.current) {
          ws.send(JSON.stringify({ action: "subscribe_system" }));
        }
        // Flush queued messages
        while (queueRef.current.length > 0 && ws.readyState === WebSocket.OPEN) {
          const payload = queueRef.current.shift();
          if (payload) ws.send(payload);
        }
      };

      ws.onmessage = (event) => {
        try {
          onEventRef.current(JSON.parse(event.data) as Record<string, unknown>);
        } catch {
          // ignore malformed payloads
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        socketRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        // onclose will fire after onerror, which triggers reconnect
      };
    }

    function scheduleReconnect() {
      if (disposed) return;
      const delay = backoffRef.current;
      backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF);
      reconnectTimerRef.current = window.setTimeout(connect, delay);
    }

    const connectTimer = window.setTimeout(connect, 50);

    return () => {
      disposed = true;
      window.clearTimeout(connectTimer);
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      socketRef.current?.close();
      socketRef.current = null;
      queueRef.current = [];
    };
  }, [isAuthenticated]);

  const sendOrQueue = useCallback((payload: string) => {
    const ws = socketRef.current;
    if (!ws) {
      queueRef.current.push(payload);
      return;
    }
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(payload);
      return;
    }
    if (ws.readyState === WebSocket.CONNECTING) {
      queueRef.current.push(payload);
      return;
    }
    if (ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
      queueRef.current.push(payload);
    }
  }, []);

  const subscribe = useCallback(
    (threadId: string) => {
      subscribedRef.current.add(threadId);
      sendOrQueue(JSON.stringify({ action: "subscribe", thread_id: threadId }));
    },
    [sendOrQueue],
  );
  const unsubscribe = useCallback(
    (threadId: string) => {
      subscribedRef.current.delete(threadId);
      sendOrQueue(JSON.stringify({ action: "unsubscribe", thread_id: threadId }));
    },
    [sendOrQueue],
  );
  const subscribeSystem = useCallback(
    () => {
      systemSubRef.current = true;
      sendOrQueue(JSON.stringify({ action: "subscribe_system" }));
    },
    [sendOrQueue],
  );

  return useMemo(
    () => ({
      subscribe,
      unsubscribe,
      subscribeSystem,
    }),
    [subscribe, subscribeSystem, unsubscribe],
  );
}
