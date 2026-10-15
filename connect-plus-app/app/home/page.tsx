import Link from "next/link";
import { AppHeader } from "../header";
import { Screen } from "../ui";
import { getUser, greeting } from "../session";
import { endSession } from "../actions";
import { RESOURCES } from "../content";
import { getProgress } from "../progress";

// Screen 2. Two paths, not three: mentor help lives in the header at all times
// rather than as a third equal card, so it is always one tap away without
// inviting someone to skip the learning.

const CARD =
  "flex min-h-[6.6rem] items-center gap-4 rounded-[0.7rem] border-2 bg-surface p-4 " +
  "text-left text-ink transition-colors focus-visible:outline-3 " +
  "focus-visible:outline-offset-3 focus-visible:outline-accent sm:min-h-[7.5rem] sm:gap-5 sm:p-5";

const ICON =
  "grid h-[3.2rem] w-[3.2rem] flex-none place-items-center rounded-[0.6rem] text-[1.5rem]";

export default async function Home() {
  const [user, last] = await Promise.all([getUser(), getProgress()]);

  return (
    <Screen>
      <AppHeader back="/home" />

      <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
        <p className="text-body text-muted">
          {greeting()}
          {user ? `, ${user.name}` : ""}
        </p>
        <h1 className="mt-1 text-heading font-medium leading-tight">
          What would you like to do?
        </h1>

        {/* two columns is the maximum, and only from 640px: the same content in
            the same order, nothing extra revealed by a wider screen */}
        <div className="mt-7 grid gap-5 sm:grid-cols-2">
          {/* one primary action per screen — Browse carries the accent border */}
          <Link href="/browse" className={`${CARD} border-accent hover:bg-[#2b2741]`}>
            <span aria-hidden="true" className={`${ICON} bg-fill text-on-fill`}>
              ▦
            </span>
            <span className="flex flex-col gap-1">
              <span className="text-body font-medium">Browse topics</span>
              <span className="text-latin text-dim">Pick what you want to learn</span>
            </span>
          </Link>

          <Link href="/ask" className={`${CARD} border-line hover:border-accent`}>
            <span aria-hidden="true" className={`${ICON} bg-panel text-ink`}>
              💬
            </span>
            <span className="flex flex-col gap-1">
              <span className="text-body font-medium">Ask a question</span>
              <span className="text-latin text-dim">Type it or say it out loud</span>
            </span>
          </Link>
        </div>

        {user && (
          <form action={endSession} className="mt-8">
            {/* quiet on purpose: signing out is rare, and a prominent one next
                to two learning cards is a trap for a mis-tap */}
            <button
              type="submit"
              className="min-h-[2.8rem] text-latin text-muted underline-offset-4 hover:text-accent hover:underline focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent"
            >
              Sign out ({user.email})
            </button>
          </form>
        )}

        {/* only shown when there is something to resume — an empty "carry on
            where you left off" panel is worse than no panel */}
        {last && (
          // the whole panel is the target — an inline link is too small to tap
          <Link
            href={`/resource/${last.id}?step=${last.step}`}
            className="mt-auto flex min-h-[2.8rem] items-center gap-3 rounded-[0.6rem] bg-panel p-4 transition-colors hover:bg-line focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent"
          >
            <span aria-hidden="true" className="text-body text-accent">
              ↺
            </span>
            <span className="flex-1 text-latin text-dim">
              Last time you were learning{" "}
              <span className="text-ink">{RESOURCES[last.id].title}</span>. Carry on
              from step {last.step}.
            </span>
          </Link>
        )}
      </main>
    </Screen>
  );
}
