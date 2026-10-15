import Link from "next/link";
import { notFound } from "next/navigation";
import { catalogue, topicOf } from "../../content";
import { AppHeader } from "../../header";
import { BTN_PRIMARY, BTN_SECONDARY, Screen } from "../../ui";
import { finish, go, practise, stuck } from "./actions";

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
  const [{ id }, sp] = await Promise.all([params, searchParams]);
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
            <span aria-hidden="true">✓ </span>Lesson finished
          </p>
          <h1 className="mt-2 text-heading font-medium leading-tight">Well done</h1>
          <p className="mt-3 text-body text-dim">
            You have finished <span className="text-ink">{r.title}</span>. You can come back
            to it at any time.
          </p>
          <Link href={topic.href} className={`${BTN_PRIMARY} mt-8 text-body`}>
            Back to {topic.title}
          </Link>
          <Link href="/home" className={`${BTN_SECONDARY} mt-4 text-body`}>
            Back to Home
          </Link>
        </main>
      </Screen>
    );
  }

  const n = Math.min(Math.max(1, Number(sp.step) || 1), total);
  const step = r.steps[n - 1];
  const here = `/resource/${id}?step=${n}`;
  const offer = Boolean(sp.offer);

  return (
    <Screen>
      <AppHeader back={here} />

      <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
        <p className="text-latin text-muted">
          {step.practice ? "Practice · " : ""}
          {r.title}
        </p>

        {/* while the offer is open the step stays visible but steps back */}
        <div className={`flex flex-col ${offer ? "opacity-50" : ""}`}>
          {/* progress is a word first; the bar only repeats it */}
          <div className="mt-3 flex items-center gap-3">
            <span className="flex-none text-latin font-medium text-dim">
              Step {n} of {total}
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
              <span aria-hidden="true">✋ </span>Your turn
            </span>
          )}
          <h1 className="mt-4 text-heading font-medium leading-tight">{step.title}</h1>
          {step.body && <p className="mt-3 text-body text-dim">{step.body}</p>}
          {step.url && (
            // a page on an approved site: the content is there, not copied
            // here, so the senior reads the original and comes back for Next
            <div className="mt-4 flex flex-col gap-3">
              <p className="text-body text-dim">
                This step is a page on{" "}
                <span className="text-ink">{r.domain ?? new URL(step.url).hostname}</span>, a
                trusted website. Open it, read it, then come back here and tap Next.
              </p>
              <a
                href={step.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`${BTN_SECONDARY} text-body`}
              >
                <span aria-hidden="true">↗</span>Open this step
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </div>
          )}

          {step.picture && (
            // ponytail: a labelled placeholder until real screenshots exist; the
            // alt text is already the finished one
            <div
              role="img"
              aria-label={step.picture}
              className="mt-5 grid min-h-[9rem] place-items-center rounded-[0.6rem] border border-line bg-[repeating-linear-gradient(45deg,var(--color-line),var(--color-line)_4px,var(--color-panel)_4px,var(--color-panel)_8px)] p-4 text-center"
            >
              <span aria-hidden="true" className="rounded bg-bg/80 px-2 text-latin text-faint">
                {step.picture}
              </span>
            </div>
          )}

          {step.practice && <PracticePhone id={id} step={n} offer={offer} />}
          {step.practice && sp.got && (
            <p role="status" className="mt-4 text-body text-link">
              <span aria-hidden="true">✓ </span>Well done. That is the pencil. On a real phone
              it opens a new message.
            </p>
          )}
          {step.practice && sp.miss && (
            <p role="status" className="mt-4 text-body text-dim">
              Not quite. The pencil is in the top right corner, next to the word Messages.
              Try again.
            </p>
          )}
          {sp.hint && (
            <p role="status" className="mt-4 rounded-[0.5rem] bg-panel p-4 text-body text-dim">
              That is alright. Read the step again slowly. If it still does not make sense,
              tap “I’m stuck” once more and we will find a person to help.
            </p>
          )}
        </div>

        {offer ? (
          <section
            aria-labelledby="offer"
            className="mt-6 rounded-[0.8rem] border-2 border-accent bg-[#262a60] p-5 shadow-[0_16px_40px_rgba(0,0,0,0.65)]"
          >
            <span
              aria-hidden="true"
              className="grid h-[3rem] w-[3rem] place-items-center rounded-[0.7rem] bg-[#353b80] text-[1.4rem]"
            >
              🤝
            </span>
            <h2 id="offer" role="status" className="mt-4 text-heading font-medium leading-tight">
              This step is a tricky one
            </h2>
            <p className="mt-3 text-body text-link">
              Would you like a person to walk through it with you? It usually takes a few
              minutes.
            </p>
            <Link href="/help" className={`${BTN_PRIMARY} mt-5 text-body`}>
              Yes, please
            </Link>
            {/* declining is a full-size button, never a small × */}
            <Link href={here} className={`${BTN_SECONDARY} mt-3 text-body`}>
              No, I’ll keep trying
            </Link>
          </section>
        ) : (
          <div className="mt-auto pt-8">
            <form action={go} className="flex gap-4">
              <input type="hidden" name="id" value={id} />
              {n === 1 ? (
                <Link href={topic.href} className={`${BTN_SECONDARY} flex-1 text-body`}>
                  <span aria-hidden="true">←</span>Back
                </Link>
              ) : (
                // Back is equal in size to Next, not in weight
                <button type="submit" name="step" value={n - 1} className={`${BTN_SECONDARY} flex-1 text-body`}>
                  <span aria-hidden="true">←</span>Back
                </button>
              )}
              {n < total ? (
                <button type="submit" name="step" value={n + 1} className={`${BTN_PRIMARY} flex-1 text-body`}>
                  Next<span aria-hidden="true">→</span>
                </button>
              ) : (
                <button type="submit" formAction={finish} className={`${BTN_PRIMARY} flex-1 text-body`}>
                  Finish<span aria-hidden="true">✓</span>
                </button>
              )}
            </form>

            <form action={stuck} className="mt-4">
              <input type="hidden" name="id" value={id} />
              <input type="hidden" name="step" value={n} />
              <button type="submit" className={QUIET}>
                <span aria-hidden="true">?</span>I’m stuck on this step
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
function PracticePhone({ id, step, offer }: { id: string; step: number; offer: boolean }) {
  const ROW =
    "flex w-full flex-col items-start rounded-[0.5rem] bg-surface p-3 text-left " +
    `transition-colors hover:bg-line ${FOCUS}`;
  return (
    <form
      action={practise}
      aria-label="Practice phone"
      className="mx-auto mt-5 w-full max-w-[17rem] rounded-[1.4rem] border-2 border-line bg-bg p-3"
    >
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="step" value={step} />
      <fieldset disabled={offer} className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between px-1">
          <span className="text-body font-semibold">Messages</span>
          <button
            type="submit"
            name="ok"
            value="1"
            aria-label="New message"
            className={`grid h-[2.4rem] w-[2.4rem] place-items-center rounded-[0.5rem] border border-line text-body hover:border-accent ${FOCUS}`}
          >
            <span aria-hidden="true">✎</span>
          </button>
        </div>
        <button type="submit" name="ok" value="0" className={ROW}>
          <span className="text-latin font-medium">Wei</span>
          <span className="text-latin text-muted">See you Sunday</span>
        </button>
        <button type="submit" name="ok" value="0" className={ROW}>
          <span className="text-latin font-medium">Dr Nguyen’s clinic</span>
          <span className="text-latin text-muted">Appointment reminder</span>
        </button>
      </fieldset>
      <p className="mt-3 text-center text-latin text-faint">
        Practice screen · nothing is sent
      </p>
    </form>
  );
}
