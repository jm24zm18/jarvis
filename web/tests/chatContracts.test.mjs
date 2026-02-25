import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const chatPagePath = path.join(__dirname, "../src/pages/chat/index.tsx");
const source = fs.readFileSync(chatPagePath, "utf8");

test("chat page sanitizes inline thread preview text", () => {
  assert.match(source, /sanitizeForInlinePreview/);
});

test("chat page includes overflow-safe wrappers for message groups", () => {
  assert.match(source, /flex min-w-0 gap-2\.5/);
  assert.match(source, /min-w-0 max-h-\[32rem\] overflow-x-auto break-words/);
});

test("chat page constrains bubble width and thread preview lines", () => {
  assert.match(source, /maxWidth: "78ch"/);
  assert.match(source, /WebkitLineClamp: 2/);
});
