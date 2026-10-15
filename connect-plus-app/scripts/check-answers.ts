// Run: node --experimental-strip-types scripts/check-answers.ts
// Two things on screen 3b that must not regress: the offline table refuses
// what it does not know, and the answer text from connectplus-llm parses into
// steps and citation markers.
import assert from "node:assert/strict";
import { blocks, local, SUGGESTIONS } from "../app/answers.ts";

const [scam, bigger, bank] = SUGGESTIONS.map(local);
assert.ok(!scam.refused && scam.citations[0].domain === "scamwatch.gov.au", "scam text answered");
assert.ok(!bigger.refused && bigger.citations[0].domain.includes("esafety"), "writing size answered");
assert.ok(bank.refused, "bank email refused — it is about email, not texts");
assert.ok(local("").refused, "empty refused");
assert.ok(local("SCAM?? TEXT!!").refused === false, "case and punctuation ignored");
assert.ok(local("is this real").refused, "one group alone is not enough");

// A real connectplus-llm answer (mock provider, stub rag).
const md =
  "Here are the steps you can take:\n\n" +
  "1. You can block a number on your phone. [1]\n" +
  "2. A scam text creates **urgency**. [2, 3]\n\n" +
  "If you need more help, we can connect you with a mentor [1].";
const b = blocks(md);
assert.deepEqual(b.map((x) => x.kind), ["p", "ol", "p"], "intro, steps, closing line");
assert.equal(b[1].kind === "ol" && b[1].items.length, 2, "two steps");
assert.deepEqual(
  b[1].kind === "ol" && b[1].items[1],
  [{ text: "A scam text creates " }, { bold: "urgency" }, { text: ". " }, { cite: 2 }, { cite: 3 }],
  "bold and a multi-source marker",
);
assert.deepEqual(blocks("- one\n- two")[0], { kind: "ul", items: [[{ text: "one" }], [{ text: "two" }]] });
assert.deepEqual(blocks("<script>x</script>")[0], { kind: "p", parts: [{ text: "<script>x</script>" }] }, "html stays text");

console.log("answers: ok");
