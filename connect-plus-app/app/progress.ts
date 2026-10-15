import { cookies } from "next/headers";
import { getResource, type Resource } from "./content";

// Where the senior is: which lesson, which step, and how many times they have
// stumbled on it. The lesson screen writes it; Home reads it to offer a
// resume, and the helper request shows it — so the helper knows what was
// already tried without the senior having to explain.
//
// ponytail: a cookie, not a table. Move it to the database with accounts.

export type Progress = { id: string; step: number; tries: number };

// what getProgress hands back: the lesson itself, resolved
export type Place = Progress & { resource: Resource };

const YEAR = { maxAge: 60 * 60 * 24 * 365, path: "/", sameSite: "lax" } as const;

export async function getProgress(): Promise<Place | null> {
  const [id, step, tries] = ((await cookies()).get("progress")?.value ?? "").split(":");
  const r = id ? await getResource(id) : undefined;
  const n = Number(step);
  // a cookie is user input: only trust a lesson and step that exist
  if (!r || !Number.isInteger(n) || n < 1 || n > r.steps.length) return null;
  return { id, step: n, tries: Math.max(0, Number(tries) || 0), resource: r };
}

export async function setProgress(p: Progress | null) {
  const jar = await cookies();
  if (p) jar.set("progress", `${p.id}:${p.step}:${p.tries}`, YEAR);
  else jar.delete("progress");
}

// Finished lessons, read by Browse for its ticks.
export async function markRead(id: string) {
  const jar = await cookies();
  const read = new Set(jar.get("read")?.value.split(",").filter(Boolean));
  read.add(id);
  jar.set("read", [...read].join(","), YEAR);
}
