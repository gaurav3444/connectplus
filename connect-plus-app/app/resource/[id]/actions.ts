"use server";

import { redirect } from "next/navigation";
import { getResource } from "../../content";
import { getProgress, markRead, setProgress } from "../../progress";

// Every move through a lesson is a form post, so progress is saved on the
// server as it happens — and it all still works with JavaScript off.

// Stumbles on one step before the helper offer stops being quiet: "I'm stuck"
// twice, or three misses on the practice screen.
const STUCK_LIMIT = 2;
const MISS_LIMIT = 3;

// Posted fields are user input: clamp them to a lesson and step that exist.
async function read(formData: FormData) {
  const r = await getResource(String(formData.get("id")));
  if (!r) redirect("/browse");
  const step = Math.min(Math.max(1, Number(formData.get("step")) || 1), r.steps.length);
  return { id: r.id, step };
}

async function tries(id: string, step: number) {
  const p = await getProgress();
  return p?.id === id && p.step === step ? p.tries : 0;
}

export async function go(formData: FormData) {
  const { id, step } = await read(formData);
  await setProgress({ id, step, tries: await tries(id, step) });
  redirect(`/resource/${id}?step=${step}`);
}

export async function finish(formData: FormData) {
  const { id } = await read(formData);
  await markRead(id);
  await setProgress(null); // nothing left to resume
  redirect(`/resource/${id}?finished=1`);
}

export async function stuck(formData: FormData) {
  const { id, step } = await read(formData);
  const n = (await tries(id, step)) + 1;
  await setProgress({ id, step, tries: n });
  redirect(`/resource/${id}?step=${step}&${n >= STUCK_LIMIT ? "offer" : "hint"}=1`);
}

export async function practise(formData: FormData) {
  const { id, step } = await read(formData);
  if (formData.get("ok") === "1") redirect(`/resource/${id}?step=${step}&got=1`);
  const n = (await tries(id, step)) + 1;
  await setProgress({ id, step, tries: n });
  redirect(`/resource/${id}?step=${step}&${n >= MISS_LIMIT ? "offer" : "miss"}=1`);
}
