import Link from "next/link";
import { notFound } from "next/navigation";
import { catalogue, topicOf } from "../../content";
import { AppHeader } from "../../header";
import type { Dict } from "../../i18n";
import { getT } from "../../t";
import { BTN_PRIMARY, BTN_SECONDARY, Screen } from "../../ui";
import { finish, go, practise, stuck } from "./actions";
import { Icon } from "../../icons";

// Screen 3c. One step per screen, in plain words, with "I'm stuck" on every
// step at a quiet weight. Each stumble is counted; after a few on the same
// step the helper offer appears in full, in context — a sheet under the step,
// not a modal, and declining it is a real button.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

const QUIET =
  "flex min-h-[2.8rem] w-full items-center justify-center gap-2 rounded-[0.5rem] border " +
  `border-faint px-4 text-body font-medium text-dim transition-colors hover:border-accent hover:text-accent ${FOCUS}`;

export default async function Lesson({ params, searchParams }: PageProps<"/resource/[id]">) {
  const [{ id }, sp, t] = await Promise.all([params, searchParams, getT()]);
  const { categories, resources } = await catalogue();
  const r = resources[id];
  if (!r) notFound();
  const topic = topicOf(categories, id);
  const total = r.steps.length;

  if (sp.finished) {
    return (
      <Screen>
        <AppHeader back={`/resource/${id}?finished=1`} />
        <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
          <p role="status" className="text-body text-link">
            <Icon name="check" className="mr-[0.3em]" />
            {t.lessonFinished}
          </p>
          <h1 className="mt-2 text-heading font-medium leading-tight">{t.wellDone}</h1>
          <p className="mt-3 text-body text-dim">
            {t.finishedPre}
            <span className="text-ink">{r.title}</span>
            {t.finishedPost}
          </p>
          <Link href={topic.href} className={`${BTN_PRIMARY} mt-8 text-body`}>
            {t.backTo(topic.title)}
          </Link>
          <Link href="/home" className={`${BTN_SECONDARY} mt-4 text-body`}>
            {t.backTo(t.home)}
          </Link>
        </main>
      </Screen>
    );
  }

  const n = Math.min(Math.max(1, Number(sp.step) || 1), total);
  const step = r.steps[n - 1];
  const here = `/resource/${id}?step=${n}`;
  const offer = Boolean(sp.offer);
  // a step with something to look at gets two columns on a laptop: the words
  // on the left, the picture or practice phone beside them
  const visual = Boolean(step.picture || step.practice);
  // while the offer is open the step stays visible but steps back
  const dim = offer ? "opacity-50" : "";

  return (
    <Screen wide={visual}>
      <AppHeader back={here} />

      {/* Phones read top to bottom in this order. On a laptop the grid lifts
          the visual into a right-hand column beside everything else. */}
      <main
        className={`flex flex-1 flex-col px-6 py-6 sm:px-10 ${
          visual ? "lg:grid lg:grid-cols-2 lg:content-start lg:gap-x-14 lg:py-10" : ""
        }`}
      >
        <p className="text-latin text-muted lg:col-start-1">
          {step.practice ? `${t.practice} · ` : ""}
          {r.title}
        </p>

        <div className={`flex flex-col lg:col-start-1 ${dim}`}>
          {/* progress is a word first; the bar only repeats it */}
          <div className="mt-3 flex items-center gap-3">
            <span className="flex-none text-latin font-medium text-dim">
              {t.stepOf(n, total)}
            </span>
            <span aria-hidden="true" className="flex flex-1 gap-1.5">
              {r.steps.map((_, i) => (
                <span
                  key={i}
                  className={`h-2 flex-1 rounded ${i < n ? "bg-accent" : "bg-line"}`}
                />
              ))}
            </span>
          </div>

          {step.practice && (
            <span className="mt-4 self-start rounded-full bg-fill px-3 py-1 text-latin font-medium text-on-fill">
              <Icon name="hand" className="mr-[0.3em]" />
              {t.yourTurn}
            </span>
          )}
          <h1 className="mt-4 text-heading font-medium leading-tight">{step.title}</h1>
          {step.body && <p className="mt-3 text-body text-dim">{step.body}</p>}
          {step.url && (
            // a page on an approved site: the content is there, not copied
            // here, so the senior reads the original and comes back for Next
            <div className="mt-4 flex flex-col gap-3">
              <p className="text-body text-dim">
                {t.externalPre}
                <span className="text-ink">{r.domain ?? new URL(step.url).hostname}</span>
                {t.externalPost}
              </p>
              <a
                href={step.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`${BTN_SECONDARY} text-body`}
              >
                <Icon name="external-link" />
                {t.openStep}
                <span className="sr-only"> {t.newTab}</span>
              </a>
            </div>
          )}
        </div>

        {visual && (
          <div className={`lg:col-start-2 lg:row-span-4 lg:row-start-1 ${dim}`}>
            {step.picture && (
              // ponytail: a labelled placeholder until real screenshots exist; the
              // alt text is already the finished one
              <div
                role="img"
                aria-label={step.picture}
                className="mt-5 grid min-h-[9rem] place-items-center rounded-[0.6rem] lg:mt-0 lg:min-h-[18rem] border border-line bg-[repeating-linear-gradient(45deg,var(--color-line),var(--color-line)_4px,var(--color-panel)_4px,var(--color-panel)_8px)] p-4 text-center"
              >
                <span aria-hidden="true" className="rounded bg-bg/80 px-2 text-latin text-faint">
                  {step.picture}
                </span>
              </div>
            )}

            {step.practice && <PracticePhone id={id} step={n} offer={offer} t={t} />}
          </div>
        )}

        <div className={`flex flex-col lg:col-start-1 ${dim}`}>
          {step.practice && sp.got && (
            <p role="status" className="mt-4 text-body text-link">
              <Icon name="check" className="mr-[0.3em]" />
              {t.practiceGot}
            </p>
          )}
          {step.practice && sp.miss && (
            <p role="status" className="mt-4 text-body text-dim">
              {t.practiceMiss}
            </p>
          )}
          {sp.hint && (
            <p role="status" className="mt-4 rounded-[0.5rem] bg-panel p-4 text-body text-dim">
              {t.stuckHint}
            </p>
          )}
        </div>

        {offer ? (
          <section
            aria-labelledby="offer"
            className="mt-6 rounded-[0.8rem] lg:col-start-1 border-2 border-accent bg-callout p-5 shadow-[0_16px_40px_var(--color-shadow)]"
          >
            <span
              aria-hidden="true"
              className="grid h-[3rem] w-[3rem] place-items-center rounded-[0.7rem] bg-callout-mark text-[1.4rem]"
            >
              <Icon name="handshake" />
            </span>
            <h2 id="offer" role="status" className="mt-4 text-heading font-medium leading-tight">
              {t.tricky}
            </h2>
            <p className="mt-3 text-body text-link">
              {t.offerBody}
            </p>
            <Link href="/help" className={`${BTN_PRIMARY} mt-5 text-body`}>
              {t.yesPlease}
            </Link>
            {/* declining is a full-size button, never a small × */}
            <Link href={here} className={`${BTN_SECONDARY} mt-3 text-body`}>
              {t.keepTrying}
            </Link>
          </section>
        ) : (
          <div className="mt-auto pt-8 lg:col-start-1">
            <form action={go} className="flex gap-4">
              <input type="hidden" name="id" value={id} />
              {n === 1 ? (
                <Link href={topic.href} className={`${BTN_SECONDARY} flex-1 text-body`}>
                  <Icon name="arrow-left" />
                  {t.stepBack}
                </Link>
              ) : (
                // Back is equal in size to Next, not in weight
                <button type="submit" name="step" value={n - 1} className={`${BTN_SECONDARY} flex-1 text-body`}>
                  <Icon name="arrow-left" />
                  {t.stepBack}
                </button>
              )}
              {n < total ? (
                <button type="submit" name="step" value={n + 1} className={`${BTN_PRIMARY} flex-1 text-body`}>
                  {t.next}
                  <Icon name="arrow-right" />
                </button>
              ) : (
                <button type="submit" formAction={finish} className={`${BTN_PRIMARY} flex-1 text-body`}>
                  {t.finish}
                  <Icon name="check" />
                </button>
              )}
            </form>

            <form action={stuck} className="mt-4">
              <input type="hidden" name="id" value={id} />
              <input type="hidden" name="step" value={n} />
              <button type="submit" className={QUIET}>
                <span aria-hidden="true">?</span>
                {t.stuck}
              </button>
            </form>
          </div>
        )}
      </main>
    </Screen>
  );
}

// ponytail: the one practice screen there is — a pretend Messages list where
// the pencil is the right tap. Make it data-driven when a second lesson needs
// practice.
function PracticePhone({ id, step, offer, t }: { id: string; step: number; offer: boolean; t: Dict }) {
  const ROW =
    "flex w-full flex-col items-start rounded-[0.5rem] bg-surface p-3 text-left " +
    `transition-colors hover:bg-line ${FOCUS}`;
  return (
    <form
      action={practise}
      aria-label={t.practicePhone}
      className="mx-auto mt-5 w-full max-w-[17rem] rounded-[1.4rem] border-2 border-line bg-bg p-3 lg:mt-0 lg:max-w-[22rem]"
    >
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="step" value={step} />
      <fieldset disabled={offer} className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between px-1">
          <span className="text-body font-semibold">{t.phoneMessages}</span>
          <button
            type="submit"
            name="ok"
            value="1"
            aria-label={t.phoneNew}
            className={`grid h-[2.4rem] w-[2.4rem] place-items-center rounded-[0.5rem] border border-line text-body hover:border-accent ${FOCUS}`}
          >
            <Icon name="pencil" />
          </button>
        </div>
        <button type="submit" name="ok" value="0" className={ROW}>
          <span className="text-latin font-medium">Wei</span>
          <span className="text-latin text-muted">{t.phoneWeiMsg}</span>
        </button>
        <button type="submit" name="ok" value="0" className={ROW}>
          <span className="text-latin font-medium">{t.phoneClinic}</span>
          <span className="text-latin text-muted">{t.phoneClinicMsg}</span>
        </button>
      </fieldset>
      <p className="mt-3 text-center text-latin text-faint">
        {t.phoneNote}
      </p>
    </form>
  );
}
