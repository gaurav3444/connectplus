import Link from "next/link";
import { cookies } from "next/headers";
import { ask, blocks, SUGGESTIONS, type Inline } from "../answers";
import { AppHeader } from "../header";
import { BackButton, BTN_PRIMARY, BTN_SECONDARY, Screen } from "../ui";
import Speak from "./speak";

// Screen 3b. The question travels in the URL (?q=), so this is a plain GET
// form: it works with JavaScript off, and Back and refresh both land on the
// same answer. A blank box is intimidating, so the empty state teaches with a
// real example and three questions to tap.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

const BOX =
  "w-full rounded-[0.6rem] border-2 border-line bg-surface px-4 py-3 text-ink " +
  `placeholder:text-faint focus:border-accent ${FOCUS}`;

const MIC =
  "flex flex-none flex-col items-center justify-center gap-1 rounded-[0.6rem] border-2 " +
  "border-line px-3 text-latin font-medium text-ink transition-colors hover:border-accent " +
  `disabled:border-accent disabled:text-accent ${FOCUS}`;

const CHIP =
  "flex min-h-[3.2rem] w-full items-center gap-3 rounded-full border-2 border-line px-4 " +
  `py-2 text-left text-body text-ink transition-colors hover:border-accent ${FOCUS}`;

export default async function Ask({ searchParams }: PageProps<"/ask">) {
  const [sp, jar] = await Promise.all([searchParams, cookies()]);
  const q = (typeof sp.q === "string" ? sp.q : "").trim();
  const helpful = sp.helpful;
  const lang = jar.get("lang")?.value ?? "en";

  if (!q) {
    return (
      <Screen>
        <AppHeader back="/ask" />
        <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
          <BackButton href="/home">Back to Home</BackButton>
          <h1 className="mt-4 text-heading font-medium leading-tight">
            <label htmlFor="q">Ask a question</label>
          </h1>

          <form action="/ask" className="mt-4 flex flex-col">
            <div className="flex items-stretch gap-3">
              {/* a real label (the heading) and a real example as placeholder */}
              <textarea
                id="q"
                name="q"
                rows={4}
                required
                placeholder="For example: how do I know if a text message is a scam?"
                className={`${BOX} min-h-[6.6rem] text-body`}
              />
              <Speak target="q" lang={lang} className={`${MIC} w-[4.4rem]`} />
            </div>
            {"q" in sp && (
              <p role="alert" className="mt-2 text-latin text-dim">
                ⚠ Type or say your question first.
              </p>
            )}
            <button type="submit" className={`${BTN_PRIMARY} mt-4 text-body`}>
              Get an answer
            </button>
          </form>

          <h2 className="mt-8 text-body font-medium text-dim">Or try one of these</h2>
          {/* chips are buttons that ask the question, not links */}
          <form action="/ask" className="mt-3">
            <ul className="flex flex-col gap-3">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button type="submit" name="q" value={s} className={CHIP}>
                    <span aria-hidden="true" className="text-accent">
                      ⌕
                    </span>
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </form>
        </main>
      </Screen>
    );
  }

  const a = await ask(q, lang);
  const unsupported = a.refused && a.reason === "unsupported language";

  return (
    <Screen>
      <AppHeader back={`/ask?q=${encodeURIComponent(q)}`} />
      <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
        <BackButton href="/ask">Back to Ask a question</BackButton>
        <p className="mt-5 rounded-[0.6rem] bg-panel px-4 py-3 text-body text-dim">
          You asked: {q}
        </p>

        {a.refused ? (
          // role=status so a screen reader hears the refusal, not just a page
          <div role="status" className="mt-6 flex flex-col">
            <span
              aria-hidden="true"
              className="grid h-[3rem] w-[3rem] place-items-center rounded-full bg-line text-[1.4rem]"
            >
              ℹ
            </span>
            <h1 className="mt-4 text-heading font-medium leading-tight">
              We don’t have a trusted answer for this
            </h1>
            {/* the service's own sentence is in the senior's language */}
            <p className="mt-3 text-body text-dim">
              {a.message ??
                "We would rather say nothing than guess. Money and scam questions are too important to get wrong."}
            </p>
            {unsupported ? (
              <Link href="/" className={`${BTN_SECONDARY} mt-4 text-body`}>
                <span aria-hidden="true">🌐</span>Choose your language
              </Link>
            ) : (
              <p className="mt-2 text-body text-muted">A real person can look at it with you.</p>
            )}

            {/* the mentor offer is the one primary action on this screen */}
            <div className="mt-6 rounded-[0.6rem] border-2 border-accent bg-surface p-4">
              <h2 className="flex items-center gap-2 text-body font-medium">
                <span aria-hidden="true">🤝</span>Talk to a person
              </h2>
              <p className="mt-1 text-latin text-dim">
                A trained volunteer, usually within a few minutes.
              </p>
              <Link href={`/help?q=${encodeURIComponent(q)}`} className={`${BTN_PRIMARY} mt-4 text-body`}>
                Ask for help
              </Link>
            </div>
            <Link href="/ask" className={`${BTN_SECONDARY} mt-4 text-body`}>
              Ask in a different way
            </Link>

            <p className="mt-6 flex gap-3 rounded-[0.5rem] bg-panel p-4 text-latin text-dim">
              <span aria-hidden="true" className="text-accent">
                🛡
              </span>
              Never send a password or a code to anyone, including us.
            </p>
          </div>
        ) : (
          <>
            <h1 className="sr-only">Answer</h1>
            <div className="mt-5 flex flex-col gap-4">
              {blocks(a.md).map((blk, i) =>
                blk.kind === "p" ? (
                  <p key={i} className="text-body leading-relaxed">
                    <Parts parts={blk.parts} />
                  </p>
                ) : (
                  <blk.kind key={i} className="flex flex-col gap-3">
                    {blk.items.map((item, j) => (
                      <li key={j} className="flex gap-3">
                        <span
                          aria-hidden="true"
                          className="grid h-[1.7rem] w-[1.7rem] flex-none place-items-center rounded-full bg-fill text-latin font-medium text-on-fill"
                        >
                          {blk.kind === "ol" ? j + 1 : "•"}
                        </span>
                        <span className="text-body text-dim">
                          <Parts parts={item} />
                        </span>
                      </li>
                    ))}
                  </blk.kind>
                ),
              )}
            </div>

            {/* provenance is visible, always: the source cards are the trust
                mechanism, numbered to match the markers in the answer */}
            <section aria-labelledby="sources" className="mt-6 flex flex-col gap-3">
              <h2 id="sources" className="text-latin text-muted">
                Where this came from
              </h2>
              {a.citations.map((c) => (
                <div
                  key={c.n}
                  className="flex items-center gap-4 rounded-[0.6rem] border border-line bg-surface p-4"
                >
                  <span
                    aria-hidden="true"
                    className="grid h-[2.6rem] w-[2.6rem] flex-none place-items-center rounded-[0.5rem] bg-panel text-body font-semibold text-accent"
                  >
                    {c.n}
                  </span>
                  <div className="flex min-w-0 flex-col">
                    <span className="text-body font-medium">{c.title}</span>
                    <span className="text-latin text-muted">{c.domain}</span>
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-latin text-link underline underline-offset-4"
                    >
                      Read the original page
                      <span className="sr-only"> (source {c.n}, opens in a new tab)</span>
                    </a>
                  </div>
                </div>
              ))}
            </section>

            <h2 className="mt-6 text-body font-medium">Was this helpful?</h2>
            {helpful === "yes" ? (
              <p role="status" className="mt-2 text-body text-dim">
                ✓ Thank you. We are glad it helped.
              </p>
            ) : helpful === "no" ? (
              <div role="status" className="mt-2 flex flex-col">
                <p className="text-body text-dim">
                  Sorry it did not help. A real person can go through it with you.
                </p>
                <Link href={`/help?q=${encodeURIComponent(q)}`} className={`${BTN_PRIMARY} mt-3 text-body`}>
                  Ask a person
                </Link>
              </div>
            ) : (
              <form action="/ask" className="mt-3 flex gap-4">
                <input type="hidden" name="q" value={q} />
                <button type="submit" name="helpful" value="yes" className={`${BTN_SECONDARY} flex-1 text-body`}>
                  <span aria-hidden="true">👍</span>Yes
                </button>
                <button type="submit" name="helpful" value="no" className={`${BTN_SECONDARY} flex-1 text-body`}>
                  <span aria-hidden="true">👎</span>No
                </button>
              </form>
            )}
          </>
        )}

        <form action="/ask" className="mt-auto flex gap-3 pt-8">
          <label htmlFor="again" className="sr-only">
            Ask something else
          </label>
          <input
            id="again"
            name="q"
            type="text"
            required
            placeholder="Ask something else…"
            className={`${BOX} min-h-[2.8rem] text-body`}
          />
          <Speak target="again" lang={lang} compact className={`${MIC} w-[2.8rem] px-0`} />
          <button type="submit" className={`${MIC} px-4 text-body`}>
            Ask
          </button>
        </form>
      </main>
    </Screen>
  );
}

// One line of answer text. Citation markers become small numbered badges that
// match the source cards — read aloud as "source 1", never as "[1]".
function Parts({ parts }: { parts: Inline[] }) {
  return parts.map((p, i) =>
    "bold" in p ? (
      <strong key={i} className="font-semibold text-ink">
        {p.bold}
      </strong>
    ) : "cite" in p ? (
      <span
        key={i}
        className="ml-1 inline-grid h-[1.2rem] min-w-[1.2rem] place-items-center rounded-full bg-panel px-1 align-middle text-[0.9rem] font-medium text-link"
      >
        <span className="sr-only">source </span>
        {p.cite}
      </span>
    ) : (
      p.text
    ),
  );
}
