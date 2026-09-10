import { createHmac, timingSafeEqual } from "node:crypto";

// The session cookie is httpOnly, so the browser cannot read it — but the user
// can still edit it by hand in devtools. Signing it means a hand-edited cookie
// is rejected rather than trusted: without this, typing someone else's address
// into the cookie signs you in as them.
//
// ponytail: an HMAC over the address, not a session table. There is no auth
// backend yet (see app/session.ts); when one lands this becomes a session id
// and the seal/unseal pair goes away.

const SECRET =
  process.env.SESSION_SECRET ?? "dev-only-secret-set-SESSION_SECRET-in-prod";

const sign = (value: string) =>
  createHmac("sha256", SECRET).update(value).digest("base64url");

export const seal = (value: string) => `${value}.${sign(value)}`;

export function unseal(sealed: string): string | null {
  // base64url has no ".", so the last one always separates value from signature
  const cut = sealed.lastIndexOf(".");
  if (cut < 1) return null;

  const expected = Buffer.from(sign(sealed.slice(0, cut)));
  const actual = Buffer.from(sealed.slice(cut + 1));
  // length check first: timingSafeEqual throws on a mismatch rather than
  // returning false
  if (actual.length !== expected.length) return null;
  return timingSafeEqual(actual, expected) ? sealed.slice(0, cut) : null;
}
