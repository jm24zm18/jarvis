import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const roadmapPagePath = path.join(__dirname, "../src/pages/admin/roadmap/index.tsx");
const source = fs.readFileSync(roadmapPagePath, "utf8");

test("roadmap page imports createFeatureRequest API", () => {
  assert.match(source, /createFeatureRequest/);
});

test("roadmap page imports setFeatureApproval API", () => {
  assert.match(source, /setFeatureApproval/);
});

test("roadmap page imports triggerFeatureBuild API", () => {
  assert.match(source, /triggerFeatureBuild/);
});

test("roadmap page imports listFeatureBuildRuns API", () => {
  assert.match(source, /listFeatureBuildRuns/);
});

test("roadmap page has create feature modal", () => {
  assert.match(source, /CreateFeatureModal/);
  assert.match(source, /New Feature Request/);
});

test("roadmap page has approval controls", () => {
  assert.match(source, /ApprovalModal/);
  assert.match(source, /decision.*approved|approved.*decision/);
  assert.match(source, /Approve/);
  assert.match(source, /Reject/);
});

test("roadmap page has build run panel", () => {
  assert.match(source, /BuildRunsPanel/);
  assert.match(source, /Run Build/);
});

test("roadmap build runs modal has live build chat pane", () => {
  assert.match(source, /Build Chat/);
  assert.match(source, /listMessages/);
  assert.match(source, /refetchInterval:\s*2500/);
});

test("roadmap build chat has events and thread quick links", () => {
  assert.match(source, /Open full Events trace/);
  assert.match(source, /Open Chat thread/);
  assert.match(source, /to=\{`\/chat\/\$\{selectedThreadId\}`\}/);
});

test("roadmap build chat contains expected empty states", () => {
  assert.match(source, /No thread attached yet/);
  assert.match(source, /Build has not produced messages yet/);
  assert.match(source, /Load older/);
});

test("roadmap page links build run traces to events page", () => {
  assert.match(source, /\/admin\/events\?trace_id=/);
});

test("roadmap trace links use client-side routing", () => {
  assert.match(source, /from "react-router-dom"/);
  assert.match(source, /<Link/);
  assert.doesNotMatch(source, /href=\{`\/admin\/events\?trace_id=/);
});

test("roadmap page has approval_status filter", () => {
  assert.match(source, /approvalFilter/);
  assert.match(source, /approval_status/);
});

test("roadmap page has all kanban columns", () => {
  assert.match(source, /Open Backlog/);
  assert.match(source, /In Progress/);
  assert.match(source, /Resolved/);
  assert.match(source, /Closed/);
});
