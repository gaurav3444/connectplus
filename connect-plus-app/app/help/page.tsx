import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { RESOURCES } from "../content";
import { AppHeader } from "../header";
import { backTo, getRequest, LANG_NAMES } from "../helpdesk";
import { getProgress } from "../progress";
import { getUser } from "../session";
import { BackButton, BTN_PRIMARY, BTN_SECONDARY, Screen } from "../ui";
import { askForHelp } from "./actions";

// Screen 3d, consent. Nothing is shared until the senior has seen exactly
// what will be shared, item by item, with its real value — informed consent,
// not a checkbox. "Not now" goes back to the exact step and sends nothing.

export default async function HelpConsent({ searchParams }: PageProps<"/help">) {
  const [sp, jar, user, p] = await Promise.all([
    searchParams,
    cookies(),
    getUser(),
    getProgress(),
  ]);
  if (getRequest(jar.get("help")?.value)) redirect("/help/session");

  const asked = typeof sp.q === "string" ? sp.q.trim().slice(0, 500) : "";
  // the question, when they came from Ask, beats a lesson from earlier
  const lesson = !asked && p ? p : undefined;
  const back = backTo({ lesson, asked: asked || undefined });
  const lang = jar.get("lang")?.value ?? "en";

  if (!user) {
    return (
      <Screen>
        <AppHeader back="/help" help={false} />
        <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
          <BackButton href={back}>Go back</BackButton>
          <h1 className="mt-5 text-heading font-medium leading-tight">
            Sign in to talk to a helper
          </h1>
          <p className="mt-3 text-body text-dim">
            Helpers are real people, so we need to know who they are talking to. Signing in
            takes a minute, and there is no password.
          </p>
          <Link href="/signin" className={`${BTN_PRIMARY} mt-7 text-body`}>
            Sign in
          </Link>
          <Link href={back} className={`${BTN_SECONDARY} mt-4 text-body`}>
            Not now
          </Link>
        </main>
      </Screen>
    );
  }

  const shared = [
    lesson && {
      icon: "📖",
      label: "What you are learning",
      value: `${RESOURCES[lesson.id].title}, step ${lesson.step}`,
    },
    lesson && {
      icon: "👣",
      label: "What you have already tried",
      value:
        lesson.tries === 0
          ? "Nothing yet on this step"
          : `${lesson.tries} ${lesson.tries === 1 ? "attempt" : "attempts"} on this step`,
    },
    asked && { icon: "💬", label: "What you asked", value: asked },
    { icon: "🌐", label: "Your language", value: LANG_NAMES[lang] ?? lang },
  ].filter((x) => !!x);

  return (
    <Screen>
      <AppHeader back="/help" help={false} />
      <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
        <BackButton href={back}>Go back</BackButton>
        <h1 className="mt-5 text-heading font-medium leading-tight">
          We’ll ask a helper to join you
        </h1>
        <p className="mt-3 text-body text-dim">
          Helpers are trained volunteers. So they can help quickly, they will see:
        </p>

        <ul className="mt-5 flex flex-col gap-3">
          {shared.map((s) => (
            <li key={s.label} className="flex items-start gap-4 rounded-[0.6rem] bg-surface p-4">
              <span aria-hidden="true" className="text-[1.3rem]">
                {s.icon}
              </span>
              <span className="flex flex-col">
                <span className="text-body font-medium">{s.label}</span>
                <span className="text-latin text-muted">{s.value}</span>
              </span>
            </li>
          ))}
        </ul>

        <p className="mt-5 flex gap-3 rounded-[0.5rem] bg-panel p-4 text-latin text-dim">
          <span aria-hidden="true" className="text-accent">
            🛡
          </span>
          They will not see your email, and will never ask for a password or a code.
        </p>

        <form action={askForHelp} className="mt-auto pt-8">
          <input type="hidden" name="q" value={asked} />
          {/* the button says exactly what it does */}
          <button type="submit" className={`${BTN_PRIMARY} text-body`}>
            Share this and ask for help
          </button>
        </form>
        <Link href={back} className={`${BTN_SECONDARY} mt-4 text-body`}>
          Not now
        </Link>
      </main>
    </Screen>
  );
}
