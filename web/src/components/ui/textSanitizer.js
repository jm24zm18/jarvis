const MODEL_CONTROL_MARKER = /<\|[^|>]+?\|>/g;
const THINK_BLOCK_RE = /<\s*(think|thinking)\s*>[\s\S]*?<\s*\/\s*\1\s*>/gi;
const THINK_TAG_RE = /<\s*\/?\s*(think|thinking)\s*>/gi;
const NORMALIZE_SPACE_RE = /[\u00A0\u2007\u202F]/g;
const HARMFUL_BIDI_RE = /[\u202A-\u202E\u2066-\u2069]/g;

function stripUnsafeControls(text) {
  let out = "";
  for (const ch of text) {
    const code = ch.charCodeAt(0);
    if (code === 9 || code === 10) {
      out += ch;
      continue;
    }
    if ((code >= 0 && code <= 31) || code === 127) {
      continue;
    }
    out += ch;
  }
  return out;
}

function baseSanitize(text) {
  let cleaned = String(text ?? "");
  cleaned = cleaned.replace(/\r\n?/g, "\n");
  cleaned = cleaned.replace(MODEL_CONTROL_MARKER, "");
  cleaned = cleaned.replace(THINK_BLOCK_RE, " ");
  cleaned = cleaned.replace(THINK_TAG_RE, " ");
  cleaned = cleaned.replace(NORMALIZE_SPACE_RE, " ");
  cleaned = stripUnsafeControls(cleaned);
  cleaned = cleaned.replace(HARMFUL_BIDI_RE, "");
  return cleaned;
}

export function sanitizeForDisplay(input) {
  const cleaned = baseSanitize(input);
  return cleaned
    .split("\n")
    .map((line) => line.replace(/[ \t]{2,}/g, " ").trimEnd())
    .join("\n")
    .trim();
}

export function sanitizeForInlinePreview(input) {
  return sanitizeForDisplay(input).replace(/\s+/g, " ").trim();
}
