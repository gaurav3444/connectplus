"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  backTo,
  cancelRequest,
  createRequest,
  endRequest,
  getRequest,
  send,
  setNotify,
} from "../helpdesk";
import { getProgress } from "../progress";
import { getUser } from "../session";

// httpOnly: the request id is the senior's key to their chat, so nothing
// client-side gets to read it.
const COOKIE = { maxAge: 60 * 60 * 6, path: "/", sameSite: "lax", httpOnly: true } as const;

async function current() {
  return getRequest((await cookies()).get("help")?.value);
}

export async function askForHelp(formData: FormData) {
  const user = await getUser();
  if (!user) redirect("/signin");
  const jar = await cookies();
  if (await current()) redirect("/help/session"); // one request at a time

  // Re-read here rather than trusting the form: only what the consent screen
  // showed is shared, and the form could have been edited.
  // Same rule as the consent screen: a question from Ask replaces the lesson.
  const asked = String(formData.get("q") ?? "").trim().slice(0, 500) || undefined;
  const p = asked ? null : await getProgress();
  const req = createRequest({
    senior: user.name,
    lang: jar.get("lang")?.value ?? "en",
    lesson: p ? { id: p.id, step: p.step } : undefined,
    tries: p?.tries ?? 0,
    asked,
  });
  jar.set("help", req.id, COOKIE);
  redirect("/help/session");
}

export async function cancelHelp() {
  const r = await current();
  if (r) cancelRequest(r.id);
  (await cookies()).delete("help");
  redirect(backTo(r));
}

export async function endHelp() {
  const r = await current();
  if (r) endRequest(r.id);
  redirect("/help/session");
}

// After the session: forget the request and go back to what they were doing.
export async function leaveHelp() {
  const r = await current();
  (await cookies()).delete("help");
  redirect(backTo(r));
}

export async function sayToHelper(formData: FormData) {
  const r = await current();
  if (r) send(r.id, "senior", String(formData.get("text") ?? "").trim());
  redirect("/help/session");
}

export async function notifyMe() {
  const r = await current();
  if (r) setNotify(r.id);
  redirect("/help/session");
}
