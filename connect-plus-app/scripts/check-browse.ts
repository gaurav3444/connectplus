// Run: node --experimental-strip-types scripts/check-browse.ts
// connectplus-rag's browse_resources rows → the Browse tree and lessons.
import assert from "node:assert/strict";
import { fromRows, type Row } from "../app/content.ts";

const row = (o: Partial<Row>): Row => ({
  category_id: "staying-safe",
  category_title: "Staying Safe Online",
  category_pos: 2,
  subcategory_id: "passwords",
  subcategory_title: "Passwords",
  subcategory_pos: 3,
  resource_pos: 0,
  resource_id: "beconnected.esafety.gov.au/topic-library/managing-passwords",
  url: "https://beconnected.esafety.gov.au/topic-library/managing-passwords",
  domain: "beconnected.esafety.gov.au",
  title: "Managing passwords",
  pages: [
    { doc_id: "a", url: "https://beconnected.esafety.gov.au/x", title: "Overview" },
    { doc_id: "b", url: "https://beconnected.esafety.gov.au/y", title: "1 What is a password" },
  ],
  ...o,
});

// out of order on purpose: positions decide, not row order
const { categories, resources } = fromRows([
  row({ resource_pos: 1, resource_id: "scamwatch.gov.au/types-of-scams/x", title: "Second", domain: "scamwatch.gov.au" }),
  row({}),
  row({ category_id: "phone-tablet", category_title: "Phone & Tablet", category_pos: 0, subcategory_id: "calls", subcategory_title: "Calls", subcategory_pos: 0 }),
]);

assert.deepEqual(categories.map((c) => c.slug), ["phone-tablet", "staying-safe"], "categories by position");
assert.equal(categories[0].icon, "📱", "known category gets its icon");
const pw = categories[1].topics![0];
assert.equal(pw.title, "Passwords");
assert.deepEqual(pw.resources!.map((id) => resources[id].title), ["Managing passwords", "Second"], "resources by position");

const id = pw.resources![0];
assert.match(id, /^[A-Za-z0-9_-]+$/, "id is one URL segment");
assert.equal(Buffer.from(id, "base64url").toString(), "beconnected.esafety.gov.au/topic-library/managing-passwords");
assert.deepEqual(resources[id].steps.map((s) => s.title), ["Overview", "1 What is a password"], "pages are the steps, landing first");
assert.equal(resources[id].steps[1].url, "https://beconnected.esafety.gov.au/y");

// the same section filed under two subcategories is one resource
const shared = categories[0].topics![0].resources![0];
assert.equal(shared, id);
assert.equal(Object.keys(resources).length, 2);

assert.deepEqual(fromRows([]).categories, [], "no rows, no tree");
console.log("browse: ok");
