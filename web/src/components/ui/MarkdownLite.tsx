import type { ReactNode } from "react";
import { parseBlocks } from "./markdownParser";
import { sanitizeForDisplay } from "./textSanitizer";

function parseInline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const tokenRe = /(\*\*(?:[^*]|\*(?!\*))+\*\*|\*(?:[^*])+\*|`[^`]+`|\[[^\]]+\]\(([^\s)]+)\))/g;
  let lastIdx = 0;
  let key = 0;

  for (const match of text.matchAll(tokenRe)) {
    const raw = match[0];
    const idx = match.index ?? 0;
    if (idx > lastIdx) {
      parts.push(text.slice(lastIdx, idx));
    }
    if (raw.startsWith("**") && raw.endsWith("**")) {
      const inner = raw.slice(2, -2);
      // Support nested italic inside bold: **bold *italic* bold**
      parts.push(<strong key={`s-${key++}`}>{parseInline(inner)}</strong>);
    } else if (raw.startsWith("*") && raw.endsWith("*")) {
      parts.push(<em key={`e-${key++}`}>{raw.slice(1, -1)}</em>);
    } else if (raw.startsWith("`") && raw.endsWith("`")) {
      parts.push(
        <code key={`c-${key++}`} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.9em] text-text2">
          {raw.slice(1, -1)}
        </code>,
      );
    } else {
      const linkMatch = raw.match(/^\[([^\]]+)\]\(([^\s)]+)\)$/);
      if (linkMatch) {
        parts.push(
          <a
            key={`a-${key++}`}
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer noopener"
            className="underline text-accent"
          >
            {linkMatch[1]}
          </a>,
        );
      } else {
        parts.push(raw);
      }
    }
    lastIdx = idx + raw.length;
  }
  if (lastIdx < text.length) {
    parts.push(text.slice(lastIdx));
  }
  return parts.length ? parts : [text];
}

export default function MarkdownLite({ content }: { content: string }) {
  const blocks = parseBlocks(sanitizeForDisplay(content));
  return (
    <div className="markdown-lite min-w-0 break-words [overflow-wrap:anywhere]">
      {blocks.map((block, idx) => {
        if (block.type === "heading") {
          const cls =
            block.level <= 2
              ? "mb-2 mt-1 text-base font-bold"
              : "mb-1 mt-1 text-sm font-semibold";
          return (
            <div key={idx} className={cls}>
              {parseInline(block.text)}
            </div>
          );
        }
        if (block.type === "hr") {
          return <hr key={idx} className="my-3 border-t border-[var(--color-border)]" />;
        }
        if (block.type === "blockquote") {
          return (
            <blockquote key={idx} className="my-2 border-l-2 border-[var(--color-border-2)] pl-3 opacity-90">
              {block.text.split("\n").map((line, lineIdx) => (
                <div key={lineIdx}>{parseInline(line)}</div>
              ))}
            </blockquote>
          );
        }
        if (block.type === "ul") {
          return (
            <ul key={idx} className="my-2 list-disc pl-5">
              {block.items.map((item, itemIdx) => (
                <li key={itemIdx}>{parseInline(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol key={idx} className="my-2 list-decimal pl-6">
              {block.items.map((item, itemIdx) => (
                <li key={itemIdx}>{parseInline(item)}</li>
              ))}
            </ol>
          );
        }
        if (block.type === "code") {
          return (
            <pre key={idx} className="my-2 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-text2">
              <code>{block.code}</code>
            </pre>
          );
        }
        if (block.type === "table") {
          return (
            <div key={idx} className="my-2 min-w-0 overflow-x-auto">
              <table className="markdown-lite-table min-w-full border-collapse text-left text-xs">
                <thead>
                  <tr>
                    {block.header.map((cell, cellIdx) => (
                      <th key={cellIdx} className="border border-[var(--color-border)] bg-surface-2 px-2 py-1 align-top">
                        {parseInline(cell)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIdx) => (
                    <tr key={rowIdx}>
                      {row.map((cell, cellIdx) => (
                        <td key={cellIdx} className="border border-[var(--color-border)] px-2 py-1 align-top">
                          {parseInline(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        const lines = block.text.split("\n");
        return (
          <p key={idx} className="my-1 min-w-0 break-words [overflow-wrap:anywhere]">
            {lines.map((line, lineIdx) => (
              <span key={lineIdx}>
                {parseInline(line)}
                {lineIdx < lines.length - 1 ? <br /> : null}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}
