import Link from "next/link";
import { cookies } from "next/headers";
import { ask, blocks, type Inline } from "../answers";
import { dict } from "../i18n";
import { AppHeader } from "../header";
import { BackButton, BTN_PRIMARY, BTN_SECONDARY, Screen } from "../ui";
import Speak from "./speak";
import { Icon } from "../icons";

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
  const t = dict(lang);

  if (!q) {
    return (
      <Screen wide>
        <AppHeader back="/ask" />
        <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
          <BackButton href="/home">{t.backTo(t.home)}</BackButton>
          <h1 className="mt-4 text-heading font-medium leading-tight">
            <label htmlFor="q">{t.ask}</label>
          </h1>

          {/* on a laptop: the question on the left, ideas beside it */}
          <div className="lg:mt-4 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
            <form action="/ask" className="mt-4 flex flex-col lg:mt-0">
              <div className="flex items-stretch gap-3">
                {/* a real label (the heading) and a real example as placeholder */}
                <textarea
                  id="q"
                  name="q"
                  rows={4}
                  required
                  placeholder={t.askPlaceholder}
                  className={`${BOX} min-h-[6.6rem] text-body`}
                />
                <Speak target="q" lang={lang} labels={t.speak} className={`${MIC} w-[4.4rem]`} />
              </div>
              {"q" in sp && (
                <p role="alert" className="mt-2 text-latin text-dim">
                  <Icon name="triangle-alert" className="mr-[0.3em]" />{t.askEmpty}
                </p>
              )}
              <button type="submit" className={`${BTN_PRIMARY} mt-4 text-body`}>
                {t.getAnswer}
              </button>
            </form>

            <section aria-labelledby="ideas" className="lg:border-l lg:border-line lg:pl-10">
              <h2 id="ideas" className="mt-8 text-body font-medium text-dim lg:mt-0">
                {t.tryThese}
              </h2>
              {/* chips are buttons that ask the question, not links; they are in
                  the senior's language, which connectplus-llm answers in */}
              <form action="/ask" className="mt-3">
                <ul className="flex flex-col gap-3">
                  {t.suggestions.map((s) => (
                    <li key={s}>
                      <button type="submit" name="q" value={s} className={CHIP}>
                        <span aria-hidden="true" className="text-accent">
                          <Icon name="search" />
                        </span>
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
              </form>
            </section>
          </div>
        </main>
      </Screen>
    );
  }

  const a = await ask(q, lang);
  const unsupported = a.refused && a.reason === "unsupported language";
  // rag often cites several passages of one page: show the page once, with
  // every number that points at it, rather than the same card three times
  const sources = a.refused
    ? []
    : Object.values(
        Object.groupBy(a.citations, (c) => c.url) as Record<string, typeof a.citations>,
      ).map((cs) => ({ ...cs[0], ns: cs.map((c) => c.n) }));

  return (
    <Screen wide>
      <AppHeader back={`/ask?q=${encodeURIComponent(q)}`} />
      <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
        <BackButton href="/ask">{t.backTo(t.ask)}</BackButton>
        <p className="mt-5 rounded-[0.6rem] bg-panel px-4 py-3 text-body text-dim">
          {t.youAsked} {q}
        </p>

        {a.refused ? (
          // role=status so a screen reader hears the refusal, not just a page
          // on a laptop: why there is no answer on the left, the person who can
          // help beside it — phones read it top to bottom in this order
          <div
            role="status"
            className="mt-6 flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-[auto_auto_1fr_auto] lg:gap-x-12"
          >
            <div className="flex flex-col lg:col-start-1 lg:row-span-3 lg:row-start-1">
              <span
                aria-hidden="true"
                className="grid h-[3rem] w-[3rem] place-items-center rounded-full bg-line text-[1.4rem]"
              >
                ℹ
              </span>
              <h1 className="mt-4 text-heading font-medium leading-tight">
                {t.noAnswerTitle}
              </h1>
              {/* the service's own sentence is in the senior's language */}
              <p className="mt-3 text-body text-dim">
                {a.message ?? t.noAnswerBody}
              </p>
              {unsupported ? (
                <Link href="/" className={`${BTN_SECONDARY} mt-4 text-body`}>
                  <Icon name="globe" />
                  {t.chooseLang}
                </Link>
              ) : (
                <p className="mt-2 text-body text-muted">{t.realPerson}</p>
              )}
            </div>

            {/* the mentor offer is the one primary action on this screen */}
            <div className="mt-6 rounded-[0.6rem] border-2 border-accent bg-surface p-4 lg:col-start-2 lg:row-start-1 lg:mt-0 lg:self-start">
              <h2 className="flex items-center gap-2 text-body font-medium">
                <Icon name="handshake" />
                {t.talkTitle}
              </h2>
              <p className="mt-1 text-latin text-dim">
                {t.talkSub}
              </p>
              <Link href={`/help?q=${encodeURIComponent(q)}`} className={`${BTN_PRIMARY} mt-4 text-body`}>
                {t.askForHelp}
              </Link>
            </div>
            <Link href="/ask" className={`${BTN_SECONDARY} mt-4 text-body lg:col-start-1 lg:row-start-4 lg:mt-6 lg:self-start lg:px-8`}>
              {t.askDifferent}
            </Link>

            <p className="mt-6 flex gap-3 rounded-[0.5rem] bg-panel p-4 text-latin text-dim lg:col-start-2 lg:row-start-2 lg:mt-4 lg:self-start">
              <span aria-hidden="true" className="text-accent">
                <Icon name="shield" />
              </span>
              {t.safety}
            </p>
          </div>
        ) : (
          // the mockup's desktop answer: the answer on the left, where it came
          // from and what to do next beside it
          <div className="mt-5 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
            <h1 className="sr-only">{t.answer}</h1>
            <div className="flex flex-col gap-4">
              {blocks(a.md).map((blk, i) =>
                blk.kind === "p" ? (
                  <p key={i} className="text-body leading-relaxed">
                    <Parts parts={blk.parts} sourceWord={t.source} />
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
                          <Parts parts={item} sourceWord={t.source} />
                        </span>
                      </li>
                    ))}
                  </blk.kind>
                ),
              )}
            </div>

            <aside className="mt-6 flex flex-col lg:sticky lg:top-6 lg:mt-0 lg:self-start lg:border-l lg:border-line lg:pl-10">
              {/* provenance is visible, always: the source cards are the trust
                  mechanism, numbered to match the markers in the answer */}
              <section aria-labelledby="sources" className="flex flex-col gap-3">
                <h2 id="sources" className="text-latin text-muted">
                  {t.sources}
                </h2>
                {sources.map((c) => (
                  <div
                    key={c.url}
                    className="flex items-center gap-4 rounded-[0.6rem] border border-line bg-surface p-4"
                  >
                    <span
                      aria-hidden="true"
                      className="grid h-[2.6rem] min-w-[2.6rem] flex-none place-items-center rounded-[0.5rem] bg-panel px-2 text-body font-semibold text-accent"
                    >
                      {c.ns.join(", ")}
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
                        {t.readOriginal}
                        <span className="sr-only">
                          {" "}
                          ({t.source} {c.ns.join(", ")}) {t.newTab}
                        </span>
                      </a>
                    </div>
                  </div>
                ))}
              </section>

              <h2 className="mt-6 text-body font-medium">{t.helpful}</h2>
              {helpful === "yes" ? (
                <p role="status" className="mt-2 text-body text-dim">
                  <Icon name="check" className="mr-[0.3em]" />{t.thanks}
                </p>
              ) : helpful === "no" ? (
                <div role="status" className="mt-2 flex flex-col">
                  <p className="text-body text-dim">
                    {t.sorry}
                  </p>
                  <Link href={`/help?q=${encodeURIComponent(q)}`} className={`${BTN_PRIMARY} mt-3 text-body`}>
                    {t.askPerson}
                  </Link>
                </div>
              ) : (
                <form action="/ask" className="mt-3 flex gap-4">
                  <input type="hidden" name="q" value={q} />
                  <button type="submit" name="helpful" value="yes" className={`${BTN_SECONDARY} flex-1 text-body`}>
                    <Icon name="thumbs-up" />
                    {t.yes}
                  </button>
                  <button type="submit" name="helpful" value="no" className={`${BTN_SECONDARY} flex-1 text-body`}>
                    <Icon name="thumbs-down" />
                    {t.no}
                  </button>
                </form>
              )}

              {/* the mockup's desktop panel ends with a quiet way to a person */}
              <p className="mt-6 hidden rounded-[0.6rem] bg-panel p-4 text-latin text-dim lg:block">
                {t.stillUnsure}{" "}
                <Link
                  href={`/help?q=${encodeURIComponent(q)}`}
                  className="font-medium text-link underline underline-offset-4"
                >
                  {t.askPerson}
                </Link>
              </p>
            </aside>
          </div>
        )}

        {/* Pinned to the bottom of the screen like a chat box, so asking again
            never means scrolling to find it; on desktop it lines up with the
            answer column, not the panel beside it */}
        <form
          action="/ask"
          className="sticky bottom-0 mt-auto flex gap-3 bg-bg pt-4 pb-4 shadow-[0_-1px_0_var(--color-line)] lg:max-w-[calc(100%-25rem)]"
        >
          <label htmlFor="again" className="sr-only">
            {t.askElse}
          </label>
          <input
            id="again"
            name="q"
            type="text"
            required
            placeholder={t.askElsePlaceholder}
            className={`${BOX} min-h-[2.8rem] text-body`}
          />
          <Speak target="again" lang={lang} labels={t.speak} compact className={`${MIC} w-[2.8rem] px-0`} />
          <button type="submit" className={`${MIC} px-4 text-body`}>
            {t.askButton}
          </button>
        </form>
      </main>
    </Screen>
  );
}

// One line of answer text. Citation markers become small numbered badges that
// match the source cards — read aloud as "source 1", never as "[1]".
function Parts({ parts, sourceWord }: { parts: Inline[]; sourceWord: string }) {
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
        <span className="sr-only">{sourceWord} </span>
        {p.cite}
      </span>
    ) : (
      p.text
    ),
  );
}
