"use server";

import { redirect } from "next/navigation";
import { endRequest, getRequest, HELPER, joinRequest, send } from "../helpdesk";

export async function join(formData: FormData) {
  const id = String(formData.get("id"));
  const r = getRequest(id);
  // someone else got there first, or the senior cancelled
  if (!r || r.ended || (r.helper && r.helper !== HELPER.name)) redirect("/m/queue?gone=1");
  if (!HELPER.langs.includes(r.lang)) redirect("/m/queue");
  joinRequest(id, HELPER.name);
  redirect(`/m/session/${id}`);
}

export async function reply(formData: FormData) {
  const id = String(formData.get("id"));
  if (getRequest(id)?.helper === HELPER.name)
    send(id, "helper", String(formData.get("text") ?? "").trim());
  redirect(`/m/session/${id}`);
}

export async function finishSession(formData: FormData) {
  const id = String(formData.get("id"));
  if (getRequest(id)?.helper === HELPER.name) endRequest(id);
  redirect("/m/queue");
}
