import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const swarmPagePath = path.join(__dirname, "../src/pages/admin/swarm/index.tsx");
const source = fs.readFileSync(swarmPagePath, "utf8");

test("swarm page imports swarm endpoints", () => {
  assert.match(source, /listSwarmTasks/);
  assert.match(source, /createSwarmTask/);
  assert.match(source, /nudgeSwarmTask/);
  assert.match(source, /cleanupSwarmTask/);
});

test("swarm page subscribes to system websocket stream", () => {
  assert.match(source, /useWebSocket/);
  assert.match(source, /subscribeSystem/);
  assert.match(source, /system\.swarm\./);
});

test("swarm page exposes create, nudge, and cleanup controls", () => {
  assert.match(source, /Create Task/);
  assert.match(source, /Nudge Worker/);
  assert.match(source, /Cleanup Task/);
  assert.match(source, /Remove worktree directory/);
});
