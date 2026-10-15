// Run: node --experimental-strip-types scripts/check-answers.ts
// The rule that matters on screen 3b: a question we have no trusted answer for
// is refused, never matched to the nearest lookalike.
import assert from "node:assert/strict";
import { answer, SUGGESTIONS } from "../app/answers.ts";

const [scam, bigger, bank] = SUGGESTIONS.map(answer);
assert.ok(!scam.refused && scam.source.domain === "scamwatch.gov.au", "scam text answered");
assert.ok(!bigger.refused && bigger.source.domain.includes("esafety"), "writing size answered");
assert.ok(bank.refused, "bank email refused — it is about email, not texts");

assert.ok(answer("").refused, "empty refused");
assert.ok(answer("SCAM?? TEXT!!").refused === false, "case and punctuation ignored");
assert.ok(answer("is this real").refused, "one group alone is not enough");

console.log("answers: ok");
