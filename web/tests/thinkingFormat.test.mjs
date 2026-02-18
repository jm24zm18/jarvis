import test from "node:test";
import assert from "node:assert/strict";

import { formatThinkingEvent, getEventKey, truncateText } from "../src/components/ui/thinkingFormat.js";

test("formats agent thought with compact preview", () => {
  const event = {
    event_type: "agent.thought",
    payload: { iteration: 1, text: "A".repeat(260) },
    created_at: "2026-02-17T00:00:00.000Z",
  };
  const formatted = formatThinkingEvent(event);
  assert.equal(formatted.kind, "thought");
  assert.equal(formatted.status, "info");
  assert.equal(formatted.title, "Thought (iteration 2)");
  assert.ok(formatted.preview.endsWith("…"));
  assert.equal(formatted.details[0].label, "Thought");
  assert.equal(formatted.details[0].value.length, 260);
});

test("formats tool.call.start argument summary and details", () => {
  const event = {
    event_type: "tool.call.start",
    payload: { tool: "web.search", arguments: { query: "docs", limit: 5, safe: true, page: 2 } },
    created_at: "2026-02-17T00:00:00.000Z",
  };
  const formatted = formatThinkingEvent(event);
  assert.equal(formatted.kind, "tool_start");
  assert.equal(formatted.preview, "args: query, limit, safe (+1)");
  assert.equal(formatted.details[0].label, "Arguments");
  assert.match(formatted.details[0].value, /"query": "docs"/);
});

test("formats tool.call.end success summary", () => {
  const event = {
    event_type: "tool.call.end",
    payload: { tool: "kb.search", result: [{ id: "1" }, { id: "2" }, { id: "3" }] },
    created_at: "2026-02-17T00:00:00.000Z",
  };
  const formatted = formatThinkingEvent(event);
  assert.equal(formatted.status, "success");
  assert.equal(formatted.title, "Tool done: kb.search");
  assert.equal(formatted.preview, "result: list(3)");
});

test("formats tool.call.end error object", () => {
  const event = {
    event_type: "tool.call.end",
    payload: {
      tool: "exec_host",
      error: { kind: "policy_deny", message: "tool denied by policy", reason: "R3: unknown tool" },
    },
    created_at: "2026-02-17T00:00:00.000Z",
  };
  const formatted = formatThinkingEvent(event);
  assert.equal(formatted.status, "error");
  assert.equal(formatted.title, "Tool failed: exec_host");
  assert.match(formatted.preview, /tool denied by policy/);
  const errorSection = formatted.details.find((section) => section.label === "Error");
  assert.ok(errorSection);
  assert.match(errorSection.value, /reason: R3: unknown tool/);
});

test("unknown event is stable and includes raw payload", () => {
  const event = {
    event_type: "channel.inbound",
    payload: { text: "hello" },
    created_at: "2026-02-17T00:00:00.000Z",
  };
  const formatted = formatThinkingEvent(event);
  assert.equal(formatted.title, "channel.inbound");
  assert.equal(formatted.status, "info");
  const raw = formatted.details.find((section) => section.raw);
  assert.ok(raw);
  assert.match(raw.value, /"text": "hello"/);
});

test("event key is deterministic and truncate helper is safe", () => {
  const event = {
    event_type: "agent.thought",
    payload: { text: "example" },
    created_at: "2026-02-17T00:00:00.000Z",
  };
  const key1 = getEventKey(event, 0);
  const key2 = getEventKey(event, 0);
  assert.equal(key1, key2);
  assert.equal(truncateText("", 5), "");
  assert.equal(truncateText("hello", 10), "hello");
  assert.equal(truncateText("helloworld", 5), "hell…");
});
