import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { BackLink, BTN_PRIMARY, Screen } from "../../ui";
import { signIn } from "../../session";
import CodeInput from "./code-input";
import { getT } from "../../t";

// Screen 1b. Six numbers, one action, and the scam warning sits on the screen
// where the code is typed — that is the moment someone is talked into reading
// it out over the phone.

async function verify(formData: FormData) {
  "use server";
  const code = String(formData.get("code") ?? "").trim();
  if (!/^\d{6}$/.test(code)) redirect("/signin/code?error=code");

  // ponytail: no auth backend yet, so any six digits pass and the session is
  // just the address. Swap this for the real check and a real session when the
  // identity provider lands — the screen itself does not change.
  const jar = await cookies();
  const email = jar.get("email")?.value;
  if (!email) redirect("/signin");
  await signIn(email);
  jar.delete("email");
  redirect("/home");
}

async function resend() {
  "use server";
  // Nothing to send yet; the screen still has to say something happened.
  redirect("/signin/code?sent=1");
}

export default async function EnterCode({
  searchParams,
}: PageProps<"/signin/code">) {
  const [{ error, sent }, jar, t] = await Promise.all([searchParams, cookies(), getT()]);
  const email = jar.get("email")?.value;
  // Landing here cold means the address was never entered — start at screen 1.
  if (!email) redirect("/signin");

  return (
    <Screen>
      <header className="flex items-center gap-2 px-6 py-4 shadow-[0_1px_0_var(--color-line)] sm:px-10">
        <BackLink href="/signin" label={t.backToSignIn} />
      </header>

      <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">{t.codeTitle}</h1>
        <p className="mt-3 text-body text-dim">
          {t.codeSentPre}
          <span className="text-ink">{email}</span>
          {t.codeSentPost}
        </p>

        <form action={verify} className="mt-7 flex flex-col" noValidate>
          <CodeInput invalid={error === "code"} label={t.codeLabel} />
          {error === "code" && (
            <p id="code-error" role="alert" className="mt-3 text-latin text-dim">
              ⚠ {t.codeError}
            </p>
          )}
          <button type="submit" className={`${BTN_PRIMARY} mt-6 text-body`}>
            {t.continue}
          </button>
        </form>

        <form action={resend}>
          <button
            type="submit"
            className="mt-4 min-h-[2.8rem] text-body font-medium text-link underline-offset-4 hover:underline focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent"
          >
            {t.resend}
          </button>
        </form>
        {sent && (
          <p role="status" className="mt-2 text-latin text-dim">
            {t.resent}
          </p>
        )}

        <div className="mt-auto flex gap-3 rounded-[0.5rem] bg-panel p-4">
          <span aria-hidden="true" className="text-body text-accent">
            🛡
          </span>
          <p className="text-latin text-dim">
            {t.codeScam}
          </p>
        </div>
      </main>
    </Screen>
  );
}
