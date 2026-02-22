import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const channelsPagePath = path.join(__dirname, "../src/pages/admin/channels/index.tsx");
const source = fs.readFileSync(channelsPagePath, "utf8");

test("admin channels page contains pairing and lifecycle controls", () => {
  assert.match(source, /Manage configured messaging channels/);
  assert.match(source, /Initialize Connection/);
  assert.match(source, /Force Re-pair/);
  assert.match(source, /Load QR/);
  assert.match(source, /Disconnect/);
  assert.match(source, /Generate/);
  assert.match(source, /placeholder="15555550123"/);
});

test("admin channels page includes QR rendering path", () => {
  assert.match(source, /alt="WhatsApp QR"/);
  assert.match(source, /qr\.startsWith\("data:"\)/);
  assert.match(source, /No QR loaded\./);
});

test("admin channels page includes disconnect diagnostics and logged-out guidance", () => {
  assert.match(source, /Last disconnect:/);
  assert.match(source, /Session logged out \(401\); automatic recovery already attempted\./);
});
