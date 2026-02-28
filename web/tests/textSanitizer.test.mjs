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

test("sanitizeForDisplay strips zero-width and directionality marks", () => {
  const input = "7\u200E:\u200F10:\u200B52";
  const output = sanitizeForDisplay(input);
  assert.equal(output, "7:10:52");
});

test("sanitizeForDisplay compacts spaced timestamp clusters", () => {
  const input = "time 7 : 1 0 : 5 2 done";
  const output = sanitizeForDisplay(input);
  assert.equal(output, "time 7:10:52 done");
});

test("sanitizeForDisplay strips unicode format controls that split numbers", () => {
  const input = "stamp 7\u2060:\u20601\u20600\u2060:\u20605\u20602";
  const output = sanitizeForDisplay(input);
  assert.equal(output, "stamp 7:10:52");
});

test("sanitizeForDisplay compacts spaced year digits", () => {
  const input = "Released in 2 0 2 4 and updated 2 0 2 5.";
  const output = sanitizeForDisplay(input);
  assert.match(output, /2024/);
  assert.match(output, /2025/);
  assert.doesNotMatch(output, /2 0 2/);
});

test("sanitizeForDisplay does not collapse short digit pairs", () => {
  const input = "step 1 of 5 and items 1 2 3";
  const output = sanitizeForDisplay(input);
  // 2-digit and 3-digit runs must stay separate
  assert.match(output, /1 of 5/);
  assert.match(output, /1 2 3/);
});

test("sanitizeForDisplay compacts spaced date with punctuation", () => {
  // "2 8 , 2 0 2 6 ." is a full spaced date — should collapse entirely
  const input = "Today is February 2 8 , 2 0 2 6 .";
  const output = sanitizeForDisplay(input);
  // digits must be collapsed
  assert.doesNotMatch(output, /2 8/);
  assert.doesNotMatch(output, /2 0 2 6/);
  // key digits present
  assert.match(output, /28/);
  assert.match(output, /2026/);
});

test("sanitizeForDisplay compacts spaced version strings", () => {
  // "U T F - 8" contains a digit, should collapse
  const input = "Encoding is U T F - 8 format";
  const output = sanitizeForDisplay(input);
  assert.match(output, /UTF-8/);
  assert.doesNotMatch(output, /U T F/);
});

test("sanitizeForDisplay does not collapse pure-letter spaced runs", () => {
  // No digit present — must not be touched (could be intentional prose)
  const input = "Choose a b c d or e";
  const output = sanitizeForDisplay(input);
  assert.match(output, /a b c d/);
});
