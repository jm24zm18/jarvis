import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const markdownLitePath = path.resolve("src/components/ui/MarkdownLite.tsx");
const markdownParserPath = path.resolve("src/components/ui/markdownParser.js");
const textSanitizerPath = path.resolve("src/components/ui/textSanitizer.js");
let markdownLiteModulePromise = null;

async function loadMarkdownLite() {
  if (markdownLiteModulePromise) return markdownLiteModulePromise;
  markdownLiteModulePromise = (async () => {
    const source = await fs.readFile(markdownLitePath, "utf8");
    const transpiled = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2020,
        jsx: ts.JsxEmit.ReactJSX,
      },
      fileName: "MarkdownLite.tsx",
    }).outputText;
    const parserUrl = pathToFileURL(markdownParserPath).href;
    const sanitizerUrl = pathToFileURL(textSanitizerPath).href;
    const rewritten = transpiled
      .replace(/"\.\/markdownParser"/g, `"${parserUrl}"`)
      .replace(/'\.\/markdownParser'/g, `'${parserUrl}'`)
      .replace(/"\.\/textSanitizer"/g, `"${sanitizerUrl}"`)
      .replace(/'\.\/textSanitizer'/g, `'${sanitizerUrl}'`);
    const tempRoot = path.resolve(".tmp");
    await fs.mkdir(tempRoot, { recursive: true });
    const tempDir = await fs.mkdtemp(path.join(tempRoot, "markdown-lite-test-"));
    const tempFile = path.join(tempDir, "MarkdownLite.mjs");
    await fs.writeFile(tempFile, rewritten, "utf8");
    const mod = await import(pathToFileURL(tempFile).href);
    await fs.rm(tempDir, { recursive: true, force: true });
    const rootEntries = await fs.readdir(tempRoot);
    if (rootEntries.length === 0) {
      await fs.rmdir(tempRoot);
    }
    return mod.default;
  })();
  return markdownLiteModulePromise;
}

test("MarkdownLite renders recovered sections and preserves emojis in final DOM", async () => {
  const MarkdownLite = await loadMarkdownLite();
  const content = [
    "The **Cross-Agent Collaboration Hub** would transform Jarvis architecture: --- ### 🧠 **Core Workflow**",
    "1. **User triggers collaboration** start flow. 2. **Orchestrator identifies relevant agents**.",
    "3. **Parallel agent execution**. 4. **Result aggregation & synthesis**.",
    "5. **User-facing polish** - The final answer includes attribution. - You can inspect analysis.",
    "Final verification ✅ then ship 🚀.",
  ].join("\n");
  const html = renderToStaticMarkup(React.createElement(MarkdownLite, { content }));
  assert.match(html, /<hr/);
  assert.match(html, /<div class="mb-1 mt-1 text-sm font-semibold">/);
  assert.match(html, /🧠/);
  assert.match(html, /<ol/);
  assert.match(html, /<ul/);
  assert.match(html, /✅/);
  assert.match(html, /🚀/);
});

test("MarkdownLite preserves composed emoji graphemes in rendered HTML", async () => {
  const MarkdownLite = await loadMarkdownLite();
  const content = "Family 👨‍👩‍👧‍👦 and coder 👩🏽‍💻 stay intact.";
  const html = renderToStaticMarkup(React.createElement(MarkdownLite, { content }));
  assert.match(html, /👨‍👩‍👧‍👦/);
  assert.match(html, /👩🏽‍💻/);
});

test("MarkdownLite strips harmful control markers without breaking emoji", async () => {
  const MarkdownLite = await loadMarkdownLite();
  const content = "Status <|analysis|> ok\u202E family 👨‍👩‍👧‍👦";
  const html = renderToStaticMarkup(React.createElement(MarkdownLite, { content }));
  assert.doesNotMatch(html, /<\|analysis\|>/);
  assert.doesNotMatch(html, /\u202E/);
  assert.match(html, /👨‍👩‍👧‍👦/);
});
