import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { seal, unseal } from "./seal";

// ponytail: the "session" is the signed-in address, signed and put in a cookie.
// There is no auth backend yet — swap the bodies of these three for a real
// session lookup and every screen keeps working unchanged.

const COOKIE = {
  maxAge: 60 * 60 * 24 * 30,
  path: "/",
  sameSite: "lax",
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
} as const;

export async function signIn(email: string) {
  (await cookies()).set("session", seal(email), COOKIE);
}

export async function signOut() {
  (await cookies()).delete("session");
  redirect("/");
}

export async function getUser() {
  const sealed = (await cookies()).get("session")?.value;
  const email = sealed ? unseal(sealed) : null;
  if (!email) return null;

  // Until real accounts exist there is no name to read, so the address stands
  // in for one — "Good morning, May" beats "Good morning, may.tan@..." on a
  // screen built for someone who struggles to read.
  const first = email.split("@")[0].split(/[._-]/)[0];
  return { email, name: first.charAt(0).toUpperCase() + first.slice(1) };
}

// A key into the dictionary (app/i18n.ts), so the greeting follows the
// chosen language.
export function greeting(now = new Date()) {
  const h = now.getHours();
  if (h < 12) return "morning";
  if (h < 18) return "afternoon";
  return "evening";
}
