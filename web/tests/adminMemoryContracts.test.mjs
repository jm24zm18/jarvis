import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const memoryPagePath = path.join(__dirname, "../src/pages/admin/memory/index.tsx");
const source = fs.readFileSync(memoryPagePath, "utf8");

test("admin memory page includes conflict review actions", () => {
  assert.match(source, /Conflict Review Queue/);
  assert.match(source, />Approve<\/Button>/);
  assert.match(source, />Reject<\/Button>/);
  assert.match(source, /resolveMutation\.mutate\(\{ uid: item\.uid, resolution: "approved" \}\)/);
  assert.match(source, /resolveMutation\.mutate\(\{ uid: item\.uid, resolution: "rejected" \}\)/);
});

test("admin memory page includes filtered consistency report workflow", () => {
  assert.match(source, /Consistency Reports/);
  assert.match(source, /label="Thread ID"/);
  assert.match(source, /label="From \(ISO\)"/);
  assert.match(source, /label="To \(ISO\)"/);
  assert.match(source, />Apply Filters<\/Button>/);
  assert.match(source, /memoryConsistencyReport\(\{/);
  assert.match(source, /thread_id: consistencyThreadId \|\| undefined/);
  assert.match(source, /from_ts: consistencyFrom \|\| undefined/);
  assert.match(source, /to_ts: consistencyTo \|\| undefined/);
});

test("admin memory page includes required state visibility sections", () => {
  assert.match(source, /Tier and Archive Stats/);
  assert.match(source, /Failure Lookup/);
  assert.match(source, /Graph Traversal Preview/);
});
