import Link from "next/link";
import { cookies } from "next/headers";
import { endSession, setTextSize, toggleContrast } from "../actions";
import { LANG_NAMES } from "../helpdesk";
import { getUser } from "../session";
import { BackButton, BTN_SECONDARY, HEADER, Screen } from "../ui";

// Screen 5, settings. Every control shows its current state in words as well
// as by look, and each change applies the moment it is pressed — no Save
// button to forget.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

const SIZES = [
  { value: "md", label: "Normal", scale: "text-[1rem]" },
  { value: "lg", label: "Bigger", scale: "text-[1.35rem]" },
  { value: "xl", label: "Biggest", scale: "text-[1.7rem]" },
];

export default async function Settings() {
  const [jar, user] = await Promise.all([cookies(), getUser()]);
  const lang = jar.get("lang")?.value ?? "en";
  const size = jar.get("text-size")?.value ?? "md";
  const high = jar.get("contrast")?.value === "high";

  return (
    <Screen>
      <header className={HEADER}>
        <BackButton href="/home">Back to Home</BackButton>
      </header>

      <main className="flex flex-1 flex-col gap-7 px-6 py-6 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">Settings</h1>

        <section className="flex flex-col gap-3">
          <h2 className="text-body font-medium">Language</h2>
          <Link
            href="/"
            className={`flex min-h-[3rem] items-center gap-3 rounded-[0.6rem] border-2 border-line bg-surface px-4 text-body hover:border-accent ${FOCUS}`}
          >
            <span aria-hidden="true">🌐</span>
            <span className="flex-1">{LANG_NAMES[lang] ?? lang}</span>
            <span className="sr-only">Change language</span>
            <span aria-hidden="true" className="text-faint">
              ›
            </span>
          </Link>
        </section>

        <section className="flex flex-col gap-3">
          <h2 id="size" className="text-body font-medium">
            Size of the writing
          </h2>
          <form action={setTextSize} role="group" aria-labelledby="size" className="flex gap-3">
            {SIZES.map((s) => {
              const on = size === s.value;
              return (
                <button
                  key={s.value}
                  type="submit"
                  name="size"
                  value={s.value}
                  aria-pressed={on}
                  className={`flex min-h-[3.4rem] flex-1 flex-col items-center justify-center rounded-[0.6rem] border-2 px-2 py-2 ${
                    on ? "border-accent bg-[#2b2741]" : "border-line hover:border-accent"
                  } ${FOCUS}`}
                >
                  <span aria-hidden="true" className={`${s.scale} font-medium leading-none`}>
                    A
                  </span>
                  {/* the word says which is chosen; the border only repeats it */}
                  <span className="mt-1 text-latin text-dim">
                    {on && <span aria-hidden="true">✓ </span>}
                    {s.label}
                  </span>
                </button>
              );
            })}
          </form>
        </section>

        <section>
          <form action={toggleContrast}>
            <button
              type="submit"
              role="switch"
              aria-checked={high}
              className={`flex min-h-[3rem] w-full items-center gap-4 rounded-[0.6rem] border-2 border-line bg-surface px-4 py-3 text-left hover:border-accent ${FOCUS}`}
            >
              <span className="flex flex-1 flex-col">
                <span className="text-body font-medium">Stronger contrast</span>
                <span className="text-latin text-dim">Black background, white writing</span>
              </span>
              <span className="text-body font-medium">{high ? "On" : "Off"}</span>
              <span
                aria-hidden="true"
                className={`flex h-[1.7rem] w-[3rem] flex-none items-center rounded-full border p-[0.15rem] ${
                  high ? "justify-end border-accent bg-fill" : "border-faint bg-line"
                }`}
              >
                <span className={`h-[1.3rem] w-[1.3rem] rounded-full ${high ? "bg-on-fill" : "bg-muted"}`} />
              </span>
            </button>
          </form>
        </section>

        {user && (
          <form action={endSession} className="mt-auto">
            <button type="submit" className={`${BTN_SECONDARY} text-body`}>
              <span aria-hidden="true">↪</span>
              Sign out
            </button>
            <p className="mt-2 text-center text-latin text-muted">Signed in as {user.email}</p>
          </form>
        )}
      </main>
    </Screen>
  );
}
