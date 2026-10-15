import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  BackLink,
  BTN_PRIMARY,
  BTN_SECONDARY,
  FIELD,
  HEADER,
  HeaderControls,
  Screen,
} from "../ui";
import { dict } from "../i18n";

// Screen 1. One job: an email address. No password to remember and no account
// wall — "Look around first" keeps the app usable for someone who will not, or
// cannot, sign in today.

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

async function sendLink(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "").trim();
  // Server-side check as well as type="email": the action is a plain POST
  // endpoint, reachable without the form.
  if (!EMAIL.test(email)) redirect("/signin?error=email");

  // httpOnly: screen 1b only needs to *show* the address, which it does on the
  // server. Nothing client-side reads it. Short life — it is a login in flight.
  (await cookies()).set("email", email, {
    maxAge: 60 * 15,
    path: "/",
    sameSite: "lax",
    httpOnly: true,
  });
  redirect("/signin/code");
}

export default async function SignIn({ searchParams }: PageProps<"/signin">) {
  const [{ error }, jar] = await Promise.all([searchParams, cookies()]);
  const lang = jar.get("lang")?.value ?? "en";
  const big = ["lg", "xl"].includes(jar.get("text-size")?.value ?? "");
  const t = dict(lang);

  return (
    <Screen>
      <header className={HEADER}>
        <BackLink href="/" label={t.back} />
        <div className="ml-auto flex items-center gap-2">
          <HeaderControls lang={lang} big={big} back="/signin" t={t} />
        </div>
      </header>

      <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">{t.signIn}</h1>
        <p className="mt-3 max-w-[30ch] text-body text-dim">
          {t.signInIntro}
        </p>

        <form action={sendLink} className="mt-7 flex flex-col" noValidate>
          <label htmlFor="email" className="mb-2 text-body font-medium text-dim">
            {t.emailLabel}
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            inputMode="email"
            placeholder="name@example.com"
            aria-describedby={error === "email" ? "email-error" : undefined}
            aria-invalid={error === "email" || undefined}
            className={`${FIELD} text-body ${error === "email" ? "border-accent" : ""}`}
          />
          {/* plain words, no error jargon, and never colour alone */}
          {error === "email" && (
            <p id="email-error" role="alert" className="mt-2 text-latin text-dim">
              ⚠ {t.emailError}
            </p>
          )}
          <button type="submit" className={`${BTN_PRIMARY} mt-5 text-body`}>
            {t.sendLink}
          </button>
        </form>

        <hr className="my-8 h-px border-0 bg-line" />

        <p className="text-body text-muted">{t.notReady}</p>
        <Link href="/home" className={`${BTN_SECONDARY} mt-3 text-body`}>
          <span aria-hidden="true">👁</span>
          {t.lookAround}
        </Link>

        <p className="mt-auto pt-8 text-latin text-faint">
          {t.accountWhy}
        </p>
      </main>
    </Screen>
  );
}
