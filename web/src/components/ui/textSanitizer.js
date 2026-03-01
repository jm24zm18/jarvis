const MODEL_CONTROL_MARKER = /<\|[^|>]+?\|>/g;
const THINK_BLOCK_RE = /<\s*(think|thinking)\s*>[\s\S]*?<\s*\/\s*\1\s*>/gi;
const THINK_TAG_RE = /<\s*\/?\s*(think|thinking)\s*>/gi;
const NORMALIZE_SPACE_RE = /[\u00A0\u2007\u202F]/g;
const HARMFUL_BIDI_RE = /[\u202A-\u202E\u2066-\u2069]/g;
const INVISIBLE_MARKERS_RE = /[\u200B\u200C\u200E\u200F\uFEFF]/g;
const SPACED_TIME_CLUSTER_RE =
  /\b\d(?:[ \t\u00A0\u2007\u202F]*\d)*(?:[ \t\u00A0\u2007\u202F]*:[ \t\u00A0\u2007\u202F]*\d(?:[ \t\u00A0\u2007\u202F]*\d)*){1,2}\b/g;
// Matches runs of 4+ single non-space chars separated by exactly one ASCII space,
// where the run starts at a word boundary (not the trailing char of a longer word).
// E.g. "2 8 , 2 0 2 6 ." or "U T F - 8". Collapsed only when run contains a digit
// (safety guard: avoids collapsing pure-letter runs like "I a m a").
const SPACED_MIXED_RUN_RE = /(?<!\S)\S(?: \S){3,}/g;
const GENERAL_SPACE_RE = /\p{Zs}/gu;

function stripFormatControlsExceptZwj(text) {
  let out = "";
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    // Keep ZWJ to preserve composed emoji graphemes like family and profession emojis.
    if (code === 0x200d) {
      out += ch;
      continue;
    }
    if (/\p{Cf}/u.test(ch)) {
      continue;
    }
    out += ch;
  }
  return out;
}

function normalizeNumericClusters(text) {
  return text
    .replace(SPACED_TIME_CLUSTER_RE, (match) => match.replace(/[ \t\u00A0\u2007\u202F]+/g, ""))
    .replace(SPACED_MIXED_RUN_RE, (match) => (/\d/.test(match) ? match.replace(/ /g, "") : match));
}

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
  cleaned = cleaned.replace(GENERAL_SPACE_RE, " ");
  cleaned = cleaned.replace(NORMALIZE_SPACE_RE, " ");
  cleaned = stripUnsafeControls(cleaned);
  cleaned = stripFormatControlsExceptZwj(cleaned);
  cleaned = cleaned.replace(HARMFUL_BIDI_RE, "");
  cleaned = cleaned.replace(INVISIBLE_MARKERS_RE, "");
  cleaned = normalizeNumericClusters(cleaned);
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
