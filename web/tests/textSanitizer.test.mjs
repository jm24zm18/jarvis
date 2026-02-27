import test from "node:test";
import assert from "node:assert/strict";

import { sanitizeForDisplay, sanitizeForInlinePreview } from "../src/components/ui/textSanitizer.js";

test("sanitizeForDisplay preserves composed emoji", () => {
  const input = "Family 👨‍👩‍👧‍👦 skin 👍🏽 flag 🇺🇸 keycap 1️⃣";
  const output = sanitizeForDisplay(input);
  assert.match(output, /👨‍👩‍👧‍👦/);
  assert.match(output, /👍🏽/);
  assert.match(output, /🇺🇸/);
  assert.match(output, /1️⃣/);
});

test("sanitizeForDisplay strips model markers and harmful controls", () => {
  const input = "ok <|analysis|>\u202E \u0007 done";
  const output = sanitizeForDisplay(input);
  assert.equal(output, "ok done");
});

test("sanitizeForDisplay strips think wrappers", () => {
  const input = "Visible <think>hidden</think> text <thinking>also hidden</thinking> end";
  const output = sanitizeForDisplay(input);
  assert.equal(output, "Visible text end");
});

test("sanitizeForInlinePreview collapses whitespace", () => {
  const input = "Hello\n\nthere   world";
  const output = sanitizeForInlinePreview(input);
  assert.equal(output, "Hello there world");
});
