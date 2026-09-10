// Run: node --experimental-strip-types scripts/check-seal.ts
// The one thing worth a check: a tampered session cookie must not sign anyone
// in. No test runner — this is a plain assert script.
import assert from "node:assert/strict";
import { seal, unseal } from "../app/seal.ts";

const email = "may.tan@example.com";
const sealed = seal(email);

assert.equal(unseal(sealed), email, "a cookie we signed reads back");

// the attack this exists to stop: editing the address in devtools
assert.equal(unseal(`someone.else@example.com.${sealed.split(".").pop()}`), null);
assert.equal(unseal(email), null, "unsigned value rejected");
assert.equal(unseal(`${email}.`), null, "empty signature rejected");
assert.equal(unseal(`${email}.short`), null, "wrong-length signature rejected");
assert.equal(unseal(sealed.slice(0, -1) + "x"), null, "flipped byte rejected");
assert.equal(unseal(""), null, "empty cookie rejected");

console.log("seal: ok");
