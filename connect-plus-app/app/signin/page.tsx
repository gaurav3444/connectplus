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
  const big = jar.get("text-size")?.value === "lg";

  return (
    <Screen>
      <header className={HEADER}>
        <BackLink href="/" label="Go back" />
        <div className="ml-auto flex items-center gap-2">
          <HeaderControls lang={lang} big={big} back="/signin" />
        </div>
      </header>

      <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">Sign in</h1>
        <p className="mt-3 max-w-[30ch] text-body text-dim">
          We will email you a link to tap. There is no password to remember.
        </p>

        <form action={sendLink} className="mt-7 flex flex-col" noValidate>
          <label htmlFor="email" className="mb-2 text-body font-medium text-dim">
            Your email address
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
              ⚠ That does not look like an email address. It should look like
              name@example.com.
            </p>
          )}
          <button type="submit" className={`${BTN_PRIMARY} mt-5 text-body`}>
            Send me a link
          </button>
        </form>

        <hr className="my-8 h-px border-0 bg-line" />

        <p className="text-body text-muted">Not ready to sign in?</p>
        <Link href="/home" className={`${BTN_SECONDARY} mt-3 text-body`}>
          <span aria-hidden="true">👁</span>
          Look around first
        </Link>

        <p className="mt-auto pt-8 text-latin text-faint">
          You only need an account to save your progress or talk to a helper.
        </p>
      </main>
    </Screen>
  );
}
