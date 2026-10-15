// Answers for screen 3b, in the shape connectplus-llm's /ask will return
// (see its README: answer + citations, or refused).
//
// ponytail: a fixed table, matched on words, until connectplus-llm has an
// endpoint to call. Swap the body of answer() for a fetch to LLM_API_URL/ask
// and the screen does not change. Anything not in the table is refused — the
// screen must never guess about money or scams.

export type Source = { title: string; domain: string; url: string };

export type Answer =
  | { refused: false; intro: string; steps: string[]; source: Source }
  | { refused: true };

type Entry = {
  // every group must have at least one word in the question
  match: string[][];
  intro: string;
  steps: string[];
  source: Source;
};

const TABLE: Entry[] = [
  {
    match: [["scam", "fake", "real"], ["text", "message", "sms"]],
    intro: "Look for these four signs. If you see any of them, do not tap the link.",
    steps: [
      "It asks you to act quickly, or says your account will close.",
      "The sender’s number is one you do not know.",
      "The web address looks almost right, but not quite.",
      "It asks for a password or a code. Real banks never do.",
    ],
    source: {
      title: "Scamwatch, ACCC",
      domain: "scamwatch.gov.au",
      url: "https://www.scamwatch.gov.au/",
    },
  },
  {
    match: [["writing", "words", "font", "letters", "text"], ["bigger", "larger", "size", "small"]],
    intro: "You can make the writing bigger on your phone in a few taps.",
    steps: [
      "Open Settings. It is the grey gear.",
      "Tap Display. On an iPhone it is called Display & Brightness.",
      "Tap Text size, or Font size.",
      "Move the slider to the right until the writing is easy to read.",
    ],
    source: {
      title: "Be Connected, eSafety Commissioner",
      domain: "beconnected.esafety.gov.au",
      url: "https://beconnected.esafety.gov.au/",
    },
  },
];

const words = (q: string) => q.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];

export function answer(q: string): Answer {
  const said = new Set(words(q));
  const hit = TABLE.find((e) => e.match.every((group) => group.some((w) => said.has(w))));
  return hit ? { refused: false, ...hit } : { refused: true };
}

// Shown on the empty screen. Chips are real questions, not categories.
export const SUGGESTIONS = [
  "How do I know if a text is a scam?",
  "How do I make the writing bigger?",
  "Is this bank email real?",
];
