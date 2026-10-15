import { randomUUID } from "node:crypto";

// Help requests and their chat: what a senior shares on screen 3d, what a
// helper sees in the queue and session (screen 4).
//
// ponytail: one in-memory store in the server process. It works for a demo
// on one machine and is lost on restart. Swap these functions for Supabase
// tables + Realtime and the screens do not change.

export type Message = { from: "senior" | "helper"; text: string; at: number };

export type HelpRequest = {
  id: string;
  senior: string;
  lang: string;
  // what the senior agreed to share, captured at the moment they asked
  lesson?: { id: string; step: number };
  tries: number;
  asked?: string;
  created: number;
  helper?: string;
  joined?: number;
  ended?: boolean;
  notify?: boolean;
  messages: Message[];
};

type Store = { requests: Map<string, HelpRequest>; helperSeen: number };

// globalThis so dev-mode reloads keep the same store
const g = globalThis as unknown as { helpdesk?: Store };
const store = (g.helpdesk ??= { requests: new Map(), helperSeen: 0 });

export const LANG_NAMES: Record<string, string> = {
  zh: "中文 · Chinese",
  vi: "Tiếng Việt · Vietnamese",
  en: "English",
};

export function createRequest(r: Omit<HelpRequest, "id" | "created" | "messages">) {
  const req: HelpRequest = { ...r, id: randomUUID(), created: Date.now(), messages: [] };
  store.requests.set(req.id, req);
  return req;
}

export const getRequest = (id: string | undefined): HelpRequest | undefined =>
  id ? store.requests.get(id) : undefined;

export function cancelRequest(id: string) {
  store.requests.delete(id);
}

export function joinRequest(id: string, helper: string) {
  const r = store.requests.get(id);
  if (r && !r.helper && !r.ended) Object.assign(r, { helper, joined: Date.now() });
  return r;
}

export function endRequest(id: string) {
  const r = store.requests.get(id);
  if (r) r.ended = true;
}

export function send(id: string, from: Message["from"], text: string) {
  const r = store.requests.get(id);
  // a cap, so one request cannot fill the server's memory
  if (r && !r.ended && text && r.messages.length < 500)
    r.messages.push({ from, text: text.slice(0, 2000), at: Date.now() });
}

export function setNotify(id: string) {
  const r = store.requests.get(id);
  if (r) r.notify = true;
}

// Oldest first: whoever has waited longest is helped first.
export const waiting = () =>
  [...store.requests.values()]
    .filter((r) => !r.helper && !r.ended)
    .sort((a, b) => a.created - b.created);

// A helper counts as available while their queue screen is open — it polls,
// and each poll marks them seen.
// ponytail: one global "someone is there" flag; per-helper presence with
// accounts.
export function helperPing() {
  store.helperSeen = Date.now();
}
export const helperAvailable = () => Date.now() - store.helperSeen < 2 * 60_000;

// Where "go back" leads after asking for help: the exact step, or the
// question, or Home.
export function backTo(r: Pick<HelpRequest, "lesson" | "asked"> | undefined) {
  if (r?.lesson) return `/resource/${r.lesson.id}?step=${r.lesson.step}`;
  if (r?.asked) return `/ask?q=${encodeURIComponent(r.asked)}`;
  return "/home";
}

export function minutes(since: number, now = Date.now()) {
  const m = Math.floor((now - since) / 60_000);
  return m < 1 ? "less than a minute" : m === 1 ? "1 minute" : `${m} minutes`;
}
