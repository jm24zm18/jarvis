import test from "node:test";
import assert from "node:assert/strict";

import { parseBlocks } from "../src/components/ui/markdownParser.js";

test("recovers malformed mixed prose + table header into paragraph + table + paragraph", () => {
  const content = [
    "I am all set with core tools: | Desired Feature | Why It Helps |",
    "|-----------------|--------------|",
    "| **Web search** | Pull latest docs |",
    "| **Shell execution** | Run commands | trailing prose should not be a table cell.",
  ].join("\n");

  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 3);
  assert.equal(blocks[0].type, "paragraph");
  assert.match(blocks[0].text, /I am all set with core tools/);
  assert.equal(blocks[1].type, "table");
  assert.deepEqual(blocks[1].header, ["Desired Feature", "Why It Helps"]);
  assert.deepEqual(blocks[1].rows, [
    ["**Web search**", "Pull latest docs"],
    ["**Shell execution**", "Run commands"],
  ]);
  assert.equal(blocks[2].type, "paragraph");
  assert.match(blocks[2].text, /trailing prose/);
});

test("parses well-formed markdown table with matching column count", () => {
  const content = [
    "Intro text.",
    "",
    "| Desired Feature | Why It Helps |",
    "| --- | --- |",
    "| Web search | Pull latest docs |",
    "| Shell execution | Run commands |",
    "",
    "Outro text.",
  ].join("\n");

  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 3);
  assert.equal(blocks[0].type, "paragraph");
  assert.equal(blocks[1].type, "table");
  assert.deepEqual(blocks[1].header, ["Desired Feature", "Why It Helps"]);
  assert.deepEqual(blocks[1].rows, [
    ["Web search", "Pull latest docs"],
    ["Shell execution", "Run commands"],
  ]);
  assert.equal(blocks[2].type, "paragraph");
});

test("recovers malformed tool-list markdown with stray asterisk and en dash", () => {
  const content = [
    "I am aware that web_search and exec_host are allowed.",
    "Now that those capabilities are available, I can:  `web_search`* – fetch real-time info from the web.",
    "",
    "`exec_host` – run shell commands on the host.",
  ].join("\n");

  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, "paragraph");
  assert.equal(blocks[1].type, "ul");
  assert.deepEqual(blocks[1].items, [
    "`web_search` - fetch real-time info from the web.",
    "`exec_host` - run shell commands on the host.",
  ]);
});

test("recovers inline list item after colon into a real unordered list", () => {
  const content = [
    "I am aware that `web_search` and `exec_host` are allowed. Now I can: * **`web_search`** – fetch real-time information.",
    "* **`exec_host`** – run shell commands on the host.",
  ].join("\n");

  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, "paragraph");
  assert.equal(blocks[1].type, "ul");
  assert.deepEqual(blocks[1].items, [
    "**`web_search`** – fetch real-time information.",
    "**`exec_host`** – run shell commands on the host.",
  ]);
});

test("splits single-line markdown with inline heading and list markers", () => {
  const content = [
    "Absolutely - a **Pomsky** is a designer dog from a **Pomeranian** and a **Siberian Husky**. ### What they look like - **Size:** Usually 10-25 lb. - **Coat:** Fluffy and double-layered. ### Temperament - **Energetic:** Very playful.",
  ].join("\n");

  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 5);
  assert.equal(blocks[0].type, "paragraph");
  assert.equal(blocks[1].type, "heading");
  assert.equal(blocks[1].text, "What they look like");
  assert.equal(blocks[2].type, "ul");
  assert.deepEqual(blocks[2].items, ["**Size:** Usually 10-25 lb.", "**Coat:** Fluffy and double-layered."]);
  assert.equal(blocks[3].type, "heading");
  assert.equal(blocks[3].text, "Temperament");
  assert.equal(blocks[4].type, "ul");
  assert.deepEqual(blocks[4].items, ["**Energetic:** Very playful."]);
});

// ── New tests for bug fixes ──

test("horizontal rule renders as hr block", () => {
  const content = "Above\n\n---\n\nBelow";
  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 3);
  assert.equal(blocks[0].type, "paragraph");
  assert.equal(blocks[1].type, "hr");
  assert.equal(blocks[2].type, "paragraph");
});

test("horizontal rule with asterisks", () => {
  const content = "Above\n\n***\n\nBelow";
  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 3);
  assert.equal(blocks[1].type, "hr");
});

test("horizontal rule with underscores", () => {
  const content = "Above\n\n___\n\nBelow";
  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 3);
  assert.equal(blocks[1].type, "hr");
});

test("back-to-back tables are parsed as separate tables", () => {
  const content = [
    "| A | B |",
    "| --- | --- |",
    "| 1 | 2 |",
    "| C | D |",
    "| --- | --- |",
    "| 3 | 4 |",
  ].join("\n");

  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, "table");
  assert.deepEqual(blocks[0].header, ["A", "B"]);
  assert.deepEqual(blocks[0].rows, [["1", "2"]]);
  assert.equal(blocks[1].type, "table");
  assert.deepEqual(blocks[1].header, ["C", "D"]);
  assert.deepEqual(blocks[1].rows, [["3", "4"]]);
});

test("orphaned table separator line does not render as paragraph text", () => {
  const content = "Some text\n|--------|------|\nMore text";
  const blocks = parseBlocks(content);
  // The separator should not appear as paragraph content
  for (const block of blocks) {
    if (block.type === "paragraph") {
      assert.doesNotMatch(block.text, /\|----/);
    }
  }
});

test("heading followed by list items are separate blocks", () => {
  const content = "### 3. Historical Origins\n- Point one\n- Point two";
  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, "heading");
  assert.equal(blocks[0].text, "3. Historical Origins");
  assert.equal(blocks[1].type, "ul");
  assert.deepEqual(blocks[1].items, ["Point one", "Point two"]);
});

test("multiple list items with inline markdown are separate items", () => {
  const content = "- **First** item\n- **Second** item\n- **Third** item";
  const blocks = parseBlocks(content);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, "ul");
  assert.equal(blocks[0].items.length, 3);
  assert.equal(blocks[0].items[0], "**First** item");
  assert.equal(blocks[0].items[1], "**Second** item");
  assert.equal(blocks[0].items[2], "**Third** item");
});
