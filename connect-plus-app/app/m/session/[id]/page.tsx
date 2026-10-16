import Link from "next/link";
import { notFound } from "next/navigation";
import { describe, getRequest, HELPER, LANG_NAMES, minutes } from "../../../helpdesk";
import Poll from "../../../poll";
import { finishSession, reply } from "../../actions";

// Screen 4, the session: the chat, with where the senior is and what they
// have tried beside it, and the guidance panel open the whole time rather
// than buried in onboarding.

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const GUIDANCE = [
  "Give one instruction at a time, then wait.",
  "Describe where things are on screen, not what they are called.",
  "Never ask for a password or a code.",
];

export default async function HelperSession({ params }: PageProps<"/m/session/[id]">) {
  const { id } = await params;
  const r = getRequest(id);
  // only the helper who joined sees the conversation
  if (!r || r.helper !== HELPER.name) notFound();

  if (r.ended) {
    return (
      <div className="flex flex-col items-start gap-3 py-10">
        <h1 className="text-[1.25rem] font-medium">Session ended</h1>
        <p className="text-muted">Thank you for helping {r.senior}.</p>
        <Link href="/m/queue" className={`rounded-md border border-accent px-3 py-1.5 text-link ${FOCUS}`}>
          Back to the queue
        </Link>
      </div>
    );
  }

  const d = describe(r);

  return (
    <>
      <Poll />
      <header className="flex flex-wrap items-center gap-3 border-b border-line pb-4">
        <Link href="/m/queue" aria-label="Back to the queue" className={`rounded-md border border-line px-2.5 py-1 hover:border-accent ${FOCUS}`}>
          <span aria-hidden="true">←</span>
        </Link>
        <div className="flex flex-col leading-tight">
          <h1 className="text-[1.1rem] font-medium">{r.senior}</h1>
          <span className="text-[0.7rem] text-muted">
            {LANG_NAMES[r.lang] ?? r.lang} · joined {minutes(r.joined ?? r.created)} ago
          </span>
        </div>
        <form action={finishSession} className="ml-auto">
          <input type="hidden" name="id" value={r.id} />
          <button type="submit" className={`rounded-md border border-line px-3 py-1.5 hover:border-accent ${FOCUS}`}>
            End session
          </button>
        </form>
      </header>

      <div className="mt-4 grid flex-1 gap-5 lg:grid-cols-[1fr_20rem]">
        <section aria-label="Conversation" className="flex min-h-[24rem] flex-col">
          <ol role="log" className="flex flex-1 flex-col gap-2.5">
            {r.messages.length === 0 && (
              <li className="text-muted">
                Say hello. {r.senior} can see your name and that you are here.
              </li>
            )}
            {r.messages.map((m, i) => (
              <li
                key={i}
                className={`max-w-[80%] rounded-xl px-3.5 py-2 ${
                  m.from === "helper"
                    ? "self-end rounded-br-sm bg-fill text-on-fill"
                    : "self-start rounded-bl-sm bg-surface"
                }`}
              >
                <span className="sr-only">{m.from === "helper" ? "You" : r.senior}: </span>
                {m.text}
              </li>
            ))}
          </ol>
          <form action={reply} className="mt-4 flex gap-2">
            <input type="hidden" name="id" value={r.id} />
            <label htmlFor="reply" className="sr-only">
              Reply to {r.senior}
            </label>
            <input
              id="reply"
              name="text"
              required
              autoComplete="off"
              placeholder={`Reply to ${r.senior}…`}
              className={`min-h-[2.2rem] flex-1 rounded-md border border-line bg-surface px-3 placeholder:text-faint focus:border-accent ${FOCUS}`}
            />
            <button type="submit" className={`rounded-md border border-accent bg-fill px-4 font-medium text-on-fill hover:bg-fill-hover ${FOCUS}`}>
              Send
            </button>
          </form>
        </section>

        <aside className="flex flex-col gap-4">
          <section className="rounded-md border border-line bg-surface p-4">
            <h2 className="text-[0.65rem] font-medium uppercase tracking-wider text-muted">
              Where {r.senior} is
            </h2>
            {r.lesson ? (
              <>
                <p className="mt-2 font-medium">{r.lesson.title}</p>
                <p className="mt-1 text-[0.7rem] text-dim">
                  Step {r.lesson.step} of {r.lesson.total} · “{r.lesson.stepTitle}”
                </p>
              </>
            ) : (
              <p className="mt-2 font-medium">{d.topic}</p>
            )}
          </section>

          <section className="rounded-md border border-line bg-surface p-4">
            <h2 className="text-[0.65rem] font-medium uppercase tracking-wider text-muted">
              Already tried
            </h2>
            <p className="mt-2">{d.tried}</p>
          </section>

          {/* guidance stays open for the whole session */}
          <section className="rounded-r-md border-l-2 border-accent bg-tint p-4">
            <h2 className="text-[0.65rem] font-medium uppercase tracking-wider text-link">
              How to help well
            </h2>
            <ul className="mt-2 flex flex-col gap-1.5 text-dim">
              {GUIDANCE.map((g) => (
                <li key={g} className="flex gap-2">
                  <span aria-hidden="true" className="text-accent">
                    •
                  </span>
                  {g}
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </>
  );
}
