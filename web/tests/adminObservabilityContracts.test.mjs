import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const governancePagePath = path.join(__dirname, "../src/pages/admin/governance/index.tsx");
const eventsPagePath = path.join(__dirname, "../src/pages/admin/events/index.tsx");
const selfupdatePagePath = path.join(__dirname, "../src/pages/admin/selfupdate/index.tsx");
const apiEndpointsPath = path.join(__dirname, "../src/api/endpoints.ts");

const governanceSource = fs.readFileSync(governancePagePath, "utf8");
const eventsSource = fs.readFileSync(eventsPagePath, "utf8");
const selfupdateSource = fs.readFileSync(selfupdatePagePath, "utf8");
const apiSource = fs.readFileSync(apiEndpointsPath, "utf8");

test("governance page includes evolution items and trace drill-down links", () => {
  assert.match(governanceSource, /governanceEvolutionItems/);
  assert.match(governanceSource, /Evolution Items/);
  assert.match(governanceSource, /Open Trace/);
  assert.match(governanceSource, /\/admin\/events\?/);
});

test("events page hydrates filters and trace selection from URL search params", () => {
  assert.match(eventsSource, /useSearchParams/);
  assert.match(eventsSource, /searchParams\.get\("trace_id"\)/);
  assert.match(eventsSource, /writeSearchParams/);
  assert.match(eventsSource, /trace_id: traceId/);
});

test("self-update page exposes direct trace handoff to events page", () => {
  assert.match(selfupdateSource, /View In Events/);
  assert.match(selfupdateSource, /\/admin\/events\?trace_id=/);
});

test("api endpoints include governance evolution-items client", () => {
  assert.match(apiSource, /export const governanceEvolutionItems/);
  assert.match(apiSource, /\/api\/v1\/governance\/evolution\/items/);
});
