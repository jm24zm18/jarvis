function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeText(value) {
  return String(value ?? "").trim();
}

export function truncateText(value, max = 180) {
  const text = normalizeText(value);
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

export function stringifyPretty(value) {
  if (value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function summarizeRecordKeys(value) {
  if (!isObject(value)) return "";
  const keys = Object.keys(value);
  if (!keys.length) return "{}";
  const shown = keys.slice(0, 3).join(", ");
  if (keys.length <= 3) return shown;
  return `${shown} (+${keys.length - 3})`;
}

function summarizeResult(value) {
  if (value === undefined) return "";
  if (value === null) return "null";
  if (typeof value === "string") return truncateText(value, 120);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `list(${value.length})`;
  if (isObject(value)) return `object(${Object.keys(value).length} keys)`;
  return String(value);
}

function parseError(payload) {
  const err = payload?.error;
  if (!err) return null;
  if (typeof err === "string") {
    const text = normalizeText(err);
    if (!text) return null;
    return { summary: truncateText(text, 140), details: text };
  }
  if (isObject(err)) {
    const kind = normalizeText(err.kind);
    const message = normalizeText(err.message);
    const reason = normalizeText(err.reason);
    const details = [kind ? `kind: ${kind}` : "", message, reason ? `reason: ${reason}` : ""]
      .filter(Boolean)
      .join("\n");
    if (!details) return null;
    const summary = truncateText(message || reason || kind || "Tool error", 140);
    return { summary, details };
  }
  return { summary: truncateText(String(err), 140), details: String(err) };
}

function classify(eventType, payload) {
  if (eventType === "agent.thought") return { kind: "thought", status: "info" };
  if (eventType === "tool.call.start") return { kind: "tool_start", status: "info" };
  if (eventType === "tool.call.end") {
    return parseError(payload)
      ? { kind: "tool_end", status: "error" }
      : { kind: "tool_end", status: "success" };
  }
  if (eventType.startsWith("model.")) {
    return eventType.includes("fallback")
      ? { kind: "model", status: "warning" }
      : { kind: "model", status: "info" };
  }
  if (eventType.startsWith("policy.")) return { kind: "policy", status: "warning" };
  if (eventType === "agent.delegated") return { kind: "delegation", status: "info" };
  if (eventType.includes("error") || eventType.includes("fail")) return { kind: "other", status: "error" };
  if (eventType.includes("end") || eventType.includes("success")) return { kind: "other", status: "success" };
  if (eventType.includes("fallback")) return { kind: "other", status: "warning" };
  return { kind: "other", status: "info" };
}

function formatTitle(eventType, payload) {
  if (eventType === "agent.thought") {
    const iteration = Number(payload?.iteration ?? 0) + 1;
    return `Thought (iteration ${iteration})`;
  }
  if (eventType === "tool.call.start") return `Tool start: ${String(payload?.tool ?? "unknown")}`;
  if (eventType === "tool.call.end") {
    const tool = String(payload?.tool ?? "unknown");
    return parseError(payload) ? `Tool failed: ${tool}` : `Tool done: ${tool}`;
  }
  if (eventType === "model.run.start") {
    const iteration = Number(payload?.iteration ?? 0) + 1;
    return `Model run start (iteration ${iteration})`;
  }
  if (eventType === "model.run.end") {
    const lane = String(payload?.lane ?? "unknown");
    return `Model run end (${lane})`;
  }
  if (eventType === "model.fallback") return "Model fallback triggered";
  if (eventType === "agent.delegated") {
    return `Delegated to ${String(payload?.to_agent ?? "worker")}`;
  }
  return eventType;
}

function formatPreview(eventType, payload) {
  if (eventType === "agent.thought") {
    const text = normalizeText(payload?.text);
    return text ? truncateText(text, 200) : "No thought text captured.";
  }
  if (eventType === "tool.call.start") {
    const summary = summarizeRecordKeys(payload?.arguments);
    return summary ? `args: ${summary}` : "No arguments";
  }
  if (eventType === "tool.call.end") {
    const err = parseError(payload);
    if (err) return `error: ${err.summary}`;
    return `result: ${summarizeResult(payload?.result) || "empty"}`;
  }
  if (eventType === "model.fallback") {
    const primary = normalizeText(payload?.primary_error);
    return primary ? truncateText(primary, 160) : "Primary model failed; switched lanes.";
  }
  return "";
}

function buildDetails(eventType, payload) {
  const details = [];
  if (eventType === "agent.thought") {
    const text = normalizeText(payload?.text);
    if (text) details.push({ label: "Thought", value: text, code: false });
  }
  if (eventType === "tool.call.start" && payload?.arguments !== undefined) {
    details.push({ label: "Arguments", value: stringifyPretty(payload.arguments), code: true });
  }
  if (eventType === "tool.call.end" && payload?.result !== undefined) {
    details.push({ label: "Result", value: stringifyPretty(payload.result), code: true });
  }
  const err = parseError(payload);
  if (err) {
    details.push({ label: "Error", value: err.details, code: false, emphasis: "error" });
  }
  details.push({ label: "Raw payload", value: stringifyPretty(payload), code: true, raw: true });
  return details;
}

export function formatThinkingEvent(event) {
  const payload = isObject(event?.payload) ? event.payload : {};
  const eventType = String(event?.event_type ?? "");
  const { kind, status } = classify(eventType, payload);
  return {
    kind,
    status,
    eventType,
    title: formatTitle(eventType, payload),
    preview: formatPreview(eventType, payload),
    details: buildDetails(eventType, payload),
  };
}

export function getEventKey(event, index) {
  const raw = `${event?.created_at ?? ""}|${event?.event_type ?? ""}|${stringifyPretty(event?.payload ?? {})}|${index}`;
  let hash = 0;
  for (let i = 0; i < raw.length; i += 1) {
    hash = (hash * 31 + raw.charCodeAt(i)) | 0;
  }
  return `${event?.created_at ?? "unknown"}-${Math.abs(hash)}`;
}
