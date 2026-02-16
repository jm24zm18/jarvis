/**
 * @typedef {{
 *  type: "heading";
 *  level: number;
 *  text: string;
 * } | {
 *  type: "paragraph";
 *  text: string;
 * } | {
 *  type: "blockquote";
 *  text: string;
 * } | {
 *  type: "ul";
 *  items: string[];
 * } | {
 *  type: "ol";
 *  items: string[];
 * } | {
 *  type: "code";
 *  lang: string;
 *  code: string;
 * } | {
 *  type: "table";
 *  header: string[];
 *  rows: string[][];
 * } | {
 *  type: "hr";
 * }} Block
 */

const TABLE_SEPARATOR = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/;
const UL_ITEM = /^\s*[-*]\s+([\s\S]*?)$/;
const OL_ITEM = /^\s*\d+\.\s+([\s\S]*?)$/;
const HEADING = /^(#{1,6})(?:\s+(.*)|\s*$|(.*))$/;
const HR_RULE = /^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/;

function normalizeMarkdown(markdown) {
  let text = markdown.replace(/\u202f/g, " ");
  text = text.replace(/:\s+\*\s+/g, ":\n* ");
  text = text.replace(/\n[ \t]*\n([ \t]*`[^`]+`\*?\s*[–-]\s+)/g, "\n$1");
  text = text.replace(/:\s{2,}(`[^`]+`)\*?\s*[–-]\s+/g, ":\n- $1 - ");
  text = text.replace(/^(\s*)(`[^`]+`)\*?\s*[–-]\s+/gm, "$1- $2 - ");
  text = text.replace(/([^\n])\s+(#{1,6}\s+)/g, "$1\n$2");
  text = text.replace(/^(#{1,6}\s+[^\n#]*?)\s+(-\s+)/gm, "$1\n$2");
  text = text.replace(/([^\n])\s+(-\s+(?=(?:\*\*[^*\n]+:\*\*|[A-Z][^:\n]{0,40}:)))/g, "$1\n$2");
  return text;
}

function parseTableRow(line) {
  const trimmed = line.trim();
  const inner = trimmed.startsWith("|") ? trimmed.slice(1) : trimmed;
  const content = inner.endsWith("|") ? inner.slice(0, -1) : inner;
  return content.split("|").map((cell) => cell.trim());
}

function detectTableStart(lines, idx) {
  if (idx + 1 >= lines.length) return null;
  const sourceLine = lines[idx].trim();
  const separatorLine = lines[idx + 1].trim();
  if (!sourceLine.includes("|") || !TABLE_SEPARATOR.test(separatorLine)) return null;
  const separatorCols = parseTableRow(separatorLine).length;
  if (separatorCols < 2) return null;

  const candidates = [sourceLine];
  if (!sourceLine.startsWith("|")) {
    const firstPipe = sourceLine.indexOf("|");
    if (firstPipe > 0) {
      candidates.push(sourceLine.slice(firstPipe));
    }
  }

  for (const candidate of candidates) {
    const header = parseTableRow(candidate);
    if (header.length === separatorCols) {
      const prefix =
        candidate === sourceLine ? "" : sourceLine.slice(0, sourceLine.indexOf("|")).trim();
      return { header, prefix };
    }
  }

  return null;
}

/**
 * @param {string} markdown
 * @returns {Block[]}
 */
export function parseBlocks(markdown) {
  const lines = normalizeMarkdown(markdown).replace(/\r\n/g, "\n").split("\n");
  /** @type {Block[]} */
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      i += 1;
      const codeLines = [];
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      blocks.push({ type: "code", lang, code: codeLines.join("\n") });
      continue;
    }

    // Horizontal rule detection
    if (HR_RULE.test(trimmed)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    const tableStart = detectTableStart(lines, i);
    if (tableStart) {
      const header = tableStart.header;
      if (tableStart.prefix) {
        blocks.push({ type: "paragraph", text: tableStart.prefix });
      }
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        // Check if this line is actually the start of a NEW table
        if (i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1].trim())) {
          break;
        }
        const row = parseTableRow(lines[i]);
        if (row.length < header.length) break;
        if (row.length > header.length) {
          rows.push(row.slice(0, header.length));
          lines[i] = row.slice(header.length).join(" | ");
          break;
        }
        rows.push(row);
        i += 1;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    const headingMatch = trimmed.match(HEADING);
    if (headingMatch) {
      const text = (headingMatch[2] ?? headingMatch[3] ?? "").trim();
      blocks.push({ type: "heading", level: headingMatch[1].length, text: text || headingMatch[1] });
      i += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push({ type: "blockquote", text: quoteLines.join("\n") });
      continue;
    }

    const ulMatch = trimmed.match(UL_ITEM);
    if (ulMatch) {
      const items = [];
      while (i < lines.length) {
        const currentLine = lines[i].trim();
        const m = currentLine.match(UL_ITEM);
        if (!m) break;
        items.push(m[1]);
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    const olMatch = trimmed.match(OL_ITEM);
    if (olMatch) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].trim().match(OL_ITEM);
        if (!m) break;
        items.push(m[1]);
        i += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    const paraLines = [];
    while (i < lines.length) {
      const candidate = lines[i].trim();
      if (!candidate) break;
      if (candidate.startsWith("```")) break;
      if (candidate.match(HEADING)) break;
      if (HR_RULE.test(candidate)) break;
      if (candidate.startsWith(">")) break;
      if (candidate.match(UL_ITEM)) break;
      if (candidate.match(OL_ITEM)) break;
      if (detectTableStart(lines, i)) break;
      // Also break if this line is a table separator (orphaned)
      if (TABLE_SEPARATOR.test(candidate)) break;
      paraLines.push(lines[i]);
      i += 1;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", text: paraLines.join("\n") });
    } else {
      // Skip unrecognized line to avoid infinite loop
      i += 1;
    }
  }

  return blocks;
}
