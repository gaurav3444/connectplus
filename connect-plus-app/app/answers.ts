// Answers for screen 3b, from connectplus-llm.
//
// connectplus-llm runs the whole pipeline — understand the question, retrieve
// from connectplus-rag, write the answer, have rag verify it — and returns one
// Answer: markdown with [n] markers, the citations they point at, or a
// refusal. rag is a library inside that process, so this is the only call.
//
// ponytail: its demo server's POST /api/ask, one JSON response. When stage
// 10's streaming endpoint lands, swap the fetch in ask() for it; the screen
// only ever sees an Answer.

export type Citation = { n: number; url: string; title: string; domain: string };

export type Answer =
  | { refused: false; md: string; citations: Citation[] }
  // `message` is the service's own refusal sentence, in the senior's language
  | { refused: true; reason: string; message?: string };

// Stays inside this server: the senior's question never goes from the browser
// straight to the service.
const API = process.env.LLM_API_URL;

// A real answer costs about a minute of CPU in rag. The same question asked
// again — or the page reloaded by "Was this helpful?" — reuses the first
// answer instead. The promise is stored, so two people asking at once share
// one run. Failures are dropped at once so the next try really retries.
//
// ponytail: in-process, lost on restart, capped at 200 entries. Move it next
// to the service if there is ever more than one app server.
const TTL = 60 * 60_000;
const g = globalThis as unknown as {
  answers?: Map<string, { at: number; answer: Promise<Answer> }>;
};
const answers = (g.answers ??= new Map());

export function ask(q: string, lang: string): Promise<Answer> {
  if (!API) return Promise.resolve(local(q));

  const key = `${lang}\n${q.trim().replace(/\s+/g, " ").toLowerCase()}`;
  const hit = answers.get(key);
  if (hit && Date.now() - hit.at < TTL) return hit.answer;

  const answer = fetchAnswer(API, q, lang);
  answers.set(key, { at: Date.now(), answer });
  answer.catch(() => answers.delete(key));
  if (answers.size > 200) answers.delete(answers.keys().next().value!);
  return answer;
}

async function fetchAnswer(api: string, q: string, lang: string): Promise<Answer> {
  const res = await fetch(`${api.replace(/\/$/, "")}/api/ask`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: q.slice(0, 500), lang }),
    cache: "no-store",
    // rag's reranker and grounding check run on the CPU: a warm answer took
    // ~90s on a laptop. Past 3 minutes, show the error screen rather than a
    // spinner with no end.
    signal: AbortSignal.timeout(180_000),
  });
  // a broken service is an error, never a refusal: "we have no trusted
  // answer" would be a lie when the fault is ours
  if (!res.ok) throw new Error(`connectplus-llm answered ${res.status}`);

  const { answer: a } = (await res.json()) as {
    answer: {
      answer_md: string;
      citations: Citation[];
      refused: boolean;
      refusal_reason: string;
    };
  };
  return a.refused
    ? { refused: true, reason: a.refusal_reason, message: a.answer_md }
    : { refused: false, md: a.answer_md, citations: a.citations };
}

// ---- offline fallback --------------------------------------------------
// With no LLM_API_URL the app still demos: a fixed table, matched on words.
// Anything not in it is refused — the screen must never guess about money
// or scams.

type Entry = {
  // every group must have at least one word in the question
  match: string[][];
  md: string;
  citation: Citation;
};

const TABLE: Entry[] = [
  {
    match: [["scam", "fake", "real"], ["text", "message", "sms"]],
    md: [
      "Look for these four signs. If you see any of them, do not tap the link.",
      "",
      "1. It asks you to act quickly, or says your account will close. [1]",
      "2. The sender’s number is one you do not know. [1]",
      "3. The web address looks almost right, but not quite. [1]",
      "4. It asks for a password or a code. Real banks never do. [1]",
    ].join("\n"),
    citation: { n: 1, title: "Scamwatch, ACCC", domain: "scamwatch.gov.au", url: "https://www.scamwatch.gov.au/" },
  },
  {
    match: [["writing", "words", "font", "letters", "text"], ["bigger", "larger", "size", "small"]],
    md: [
      "You can make the writing bigger on your phone in a few taps.",
      "",
      "1. Open Settings. It is the grey gear. [1]",
      "2. Tap Display. On an iPhone it is called Display & Brightness. [1]",
      "3. Tap Text size, or Font size. [1]",
      "4. Move the slider to the right until the writing is easy to read. [1]",
    ].join("\n"),
    citation: {
      n: 1,
      title: "Be Connected, eSafety Commissioner",
      domain: "beconnected.esafety.gov.au",
      url: "https://beconnected.esafety.gov.au/",
    },
  },
];

const words = (q: string) => q.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];

export function local(q: string): Answer {
  const said = new Set(words(q));
  const hit = TABLE.find((e) => e.match.every((group) => group.some((w) => said.has(w))));
  return hit
    ? { refused: false, md: hit.md, citations: [hit.citation] }
    : { refused: true, reason: "no trusted sources" };
}

// Shown on the empty screen. Chips are real questions, not categories.
export const SUGGESTIONS = [
  "How do I know if a text is a scam?",
  "How do I make the writing bigger?",
  "Is this bank email real?",
];

// ---- answer text --------------------------------------------------------
// The service writes a small, fixed slice of markdown: paragraphs, numbered
// steps, the odd bullet, **bold**, and [n] citation markers. Parsed here
// rather than with a markdown library — and never as raw HTML, since the text
// comes from a model.

export type Inline = { text: string } | { bold: string } | { cite: number };
export type Block =
  | { kind: "p"; parts: Inline[] }
  | { kind: "ol" | "ul"; items: Inline[][] };

function inline(s: string): Inline[] {
  const out: Inline[] = [];
  // [1] or [1, 2] markers, and **bold**
  for (const m of s.split(/(\*\*[^*]+\*\*|\[\d+(?:\s*,\s*\d+)*\])/)) {
    if (!m) continue;
    if (m.startsWith("**") && m.endsWith("**")) out.push({ bold: m.slice(2, -2) });
    else if (/^\[\d/.test(m)) for (const n of m.match(/\d+/g)!) out.push({ cite: Number(n) });
    else out.push({ text: m });
  }
  return out;
}

export function blocks(md: string): Block[] {
  const out: Block[] = [];
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    const ol = line.match(/^\d+[.)]\s+(.*)/);
    const ul = line.match(/^[-*•]\s+(.*)/);
    const kind = ol ? "ol" : ul ? "ul" : null;
    const last = out[out.length - 1];
    if (!line) continue;
    if (kind) {
      const item = inline((ol ?? ul)![1]);
      if (last?.kind === kind) last.items.push(item);
      else out.push({ kind, items: [item] });
    } else out.push({ kind: "p", parts: inline(line.replace(/^#+\s*/, "")) });
  }
  return out;
}
