const INVISIBLE_MARKERS_RE = /[\u200B\u200C\u200E\u200F\uFEFF\u202A-\u202E\u2066-\u2069]/g;
const NORMALIZE_SPACE_RE = /[\u00A0\u2007\u202F]/g;
const GENERAL_SPACE_RE = /\p{Zs}/gu;
const SPACED_TIME_CLUSTER_RE =
  /\b\d(?:[ \t\u00A0\u2007\u202F]*\d)*(?:[ \t\u00A0\u2007\u202F]*:[ \t\u00A0\u2007\u202F]*\d(?:[ \t\u00A0\u2007\u202F]*\d)*){1,2}\b/g;

function stripFormatControlsExceptZwj(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code === 0x200d) {
      out += ch;
      continue;
    }
    if (/\p{Cf}/u.test(ch)) continue;
    out += ch;
  }
  return out;
}

function normalizeDisplayText(value: string): string {
  return stripFormatControlsExceptZwj(value)
    .replace(GENERAL_SPACE_RE, " ")
    .replace(INVISIBLE_MARKERS_RE, "")
    .replace(NORMALIZE_SPACE_RE, " ")
    .replace(
      SPACED_TIME_CLUSTER_RE,
      (match) => match.replace(/[ \t\u00A0\u2007\u202F]+/g, ""),
    );
}

function safeDateTimeFormat(
  date: Date,
  primary: Intl.DateTimeFormatOptions,
  fallback: Intl.DateTimeFormatOptions,
): string {
  try {
    return new Intl.DateTimeFormat(undefined, primary).format(date);
  } catch {
    return new Intl.DateTimeFormat(undefined, fallback).format(date);
  }
}

export function formatTimestampHuman(value: string | Date | null | undefined): string {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return normalizeDisplayText(
    safeDateTimeFormat(
      date,
      {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZoneName: "short",
      },
      {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      },
    ),
  );
}

export function formatTimeHuman(value: string | Date | null | undefined): string {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return normalizeDisplayText(
    safeDateTimeFormat(
      date,
      {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      },
      {
        hour: "2-digit",
        minute: "2-digit",
      },
    ),
  );
}

export function formatBytesHuman(bytes: number | null | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let size = bytes;
  let idx = 0;
  while (Math.abs(size) >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  if (idx === 0) {
    return `${Math.round(size).toLocaleString()} ${units[idx]}`;
  }
  return `${size.toFixed(1)} ${units[idx]}`;
}

export function formatIntHuman(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return Math.trunc(value).toLocaleString();
}

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return `${value.toFixed(Math.max(0, decimals))}%`;
}
