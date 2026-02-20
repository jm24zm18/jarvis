import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const channelsPagePath = path.join(__dirname, "../src/pages/admin/channels/index.tsx");
const source = fs.readFileSync(channelsPagePath, "utf8");

test("admin channels page contains pairing and lifecycle controls", () => {
  assert.match(source, /Manage WhatsApp Evolution pairing and status/);
  assert.match(source, /Create\/Connect Instance/);
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
