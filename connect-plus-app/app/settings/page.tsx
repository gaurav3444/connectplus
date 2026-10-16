import Link from "next/link";
import { cookies } from "next/headers";
import { endSession, setTextSize, toggleContrast, toggleTheme } from "../actions";
import { dict, LANG_LABEL, type Dict } from "../i18n";
import { getUser } from "../session";
import { BackButton, BTN_SECONDARY, HEADER, Screen } from "../ui";

// Screen 5, settings. Every control shows its current state in words as well
// as by look, and each change applies the moment it is pressed — no Save
// button to forget.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

const SIZES = [
  { value: "md", label: "sizeNormal", scale: "text-[1rem]" },
  { value: "lg", label: "sizeBigger", scale: "text-[1.35rem]" },
  { value: "xl", label: "sizeBiggest", scale: "text-[1.7rem]" },
] as const;

// An on/off setting: the state is said in words, the track only repeats it.
function Switch({
  action,
  on,
  label,
  sub,
  t,
}: {
  action: () => Promise<void>;
  on: boolean;
  label: string;
  sub: string;
  t: Dict;
}) {
  return (
    <form action={action}>
      <button
        type="submit"
        role="switch"
        aria-checked={on}
        className={`flex min-h-[3rem] w-full items-center gap-4 rounded-[0.6rem] border-2 border-line bg-surface px-4 py-3 text-left hover:border-accent ${FOCUS}`}
      >
        <span className="flex flex-1 flex-col">
          <span className="text-body font-medium">{label}</span>
          <span className="text-latin text-dim">{sub}</span>
        </span>
        <span className="text-body font-medium">{on ? t.on : t.off}</span>
        <span
          aria-hidden="true"
          className={`flex h-[1.7rem] w-[3rem] flex-none items-center rounded-full border p-[0.15rem] ${
            on ? "justify-end border-accent bg-fill" : "border-faint bg-line"
          }`}
        >
          <span className={`h-[1.3rem] w-[1.3rem] rounded-full ${on ? "bg-on-fill" : "bg-muted"}`} />
        </span>
      </button>
    </form>
  );
}

export default async function Settings() {
  const [jar, user] = await Promise.all([cookies(), getUser()]);
  const lang = jar.get("lang")?.value ?? "en";
  const t = dict(lang);
  const size = jar.get("text-size")?.value ?? "md";
  const high = jar.get("contrast")?.value === "high";
  const light = jar.get("theme")?.value === "light";

  return (
    <Screen>
      <header className={HEADER}>
        <BackButton href="/home">{t.backTo(t.home)}</BackButton>
      </header>

      <main className="flex flex-1 flex-col gap-7 px-6 py-6 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">{t.settings}</h1>

        <section className="flex flex-col gap-3">
          <h2 className="text-body font-medium">{t.language}</h2>
          <Link
            href="/"
            className={`flex min-h-[3rem] items-center gap-3 rounded-[0.6rem] border-2 border-line bg-surface px-4 text-body hover:border-accent ${FOCUS}`}
          >
            <span aria-hidden="true">🌐</span>
            <span lang={lang} className="flex-1">
              {LANG_LABEL[lang] ?? lang}
            </span>
            <span className="sr-only">{t.changeLang}</span>
            <span aria-hidden="true" className="text-faint">
              ›
            </span>
          </Link>
        </section>

        <section className="flex flex-col gap-3">
          <h2 id="size" className="text-body font-medium">
            {t.textSize}
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
                    on ? "border-accent bg-tint" : "border-line hover:border-accent"
                  } ${FOCUS}`}
                >
                  <span aria-hidden="true" className={`${s.scale} font-medium leading-none`}>
                    A
                  </span>
                  {/* the word says which is chosen; the border only repeats it */}
                  <span className="mt-1 text-latin text-dim">
                    {on && <span aria-hidden="true">✓ </span>}
                    {t[s.label]}
                  </span>
                </button>
              );
            })}
          </form>
        </section>

        <section className="flex flex-col gap-3">
          <Switch action={toggleTheme} on={light} label={t.light} sub={t.lightSub} t={t} />
          <Switch action={toggleContrast} on={high} label={t.contrast} sub={t.contrastSub} t={t} />
        </section>

        {user && (
          <form action={endSession} className="mt-auto">
            <button type="submit" className={`${BTN_SECONDARY} text-body`}>
              <span aria-hidden="true">↪</span>
              {t.signOut}
            </button>
            <p className="mt-2 text-center text-latin text-muted">{t.signedInAs(user.email)}</p>
          </form>
        )}
      </main>
    </Screen>
  );
}
