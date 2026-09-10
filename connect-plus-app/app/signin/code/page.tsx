import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { BackLink, BTN_PRIMARY, Screen } from "../ui";
import CodeInput from "./code-input";

// Screen 1b. Six numbers, one action, and the scam warning sits on the screen
// where the code is typed — that is the moment someone is talked into reading
// it out over the phone.

async function verify(formData: FormData) {
  "use server";
  const code = String(formData.get("code") ?? "").trim();
  if (!/^\d{6}$/.test(code)) redirect("/signin/code?error=code");

  // ponytail: no auth backend yet, so any six digits pass. Swap this for the
  // real check when the identity provider lands — the screen does not change.
  (await cookies()).delete("email");
  redirect("/");
}

async function resend() {
  "use server";
  // Nothing to send yet; the screen still has to say something happened.
  redirect("/signin/code?sent=1");
}

export default async function EnterCode({
  searchParams,
}: PageProps<"/signin/code">) {
  const [{ error, sent }, jar] = await Promise.all([searchParams, cookies()]);
  const email = jar.get("email")?.value;
  // Landing here cold means the address was never entered — start at screen 1.
  if (!email) redirect("/signin");

  return (
    <Screen>
      <header className="flex items-center gap-2 px-6 py-4 shadow-[0_1px_0_var(--color-line)] sm:px-10">
        <BackLink href="/signin" label="Go back to sign in" />
      </header>

      <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">Enter your code</h1>
        <p className="mt-3 text-body text-dim">
          We sent six numbers to <span className="text-ink">{email}</span>. Type
          them below.
        </p>

        <form action={verify} className="mt-7 flex flex-col" noValidate>
          <CodeInput invalid={error === "code"} />
          {error === "code" && (
            <p id="code-error" role="alert" className="mt-3 text-latin text-dim">
              ⚠ That is not six numbers. Check the email and try again.
            </p>
          )}
          <button type="submit" className={`${BTN_PRIMARY} mt-6 text-body`}>
            Continue
          </button>
        </form>

        <form action={resend}>
          <button
            type="submit"
            className="mt-4 min-h-[2.8rem] text-body font-medium text-link underline-offset-4 hover:underline focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent"
          >
            Send the code again
          </button>
        </form>
        {sent && (
          <p role="status" className="mt-2 text-latin text-dim">
            Sent. It can take a minute to arrive.
          </p>
        )}

        <div className="mt-auto flex gap-3 rounded-[0.5rem] bg-panel p-4">
          <span aria-hidden="true" className="text-body text-accent">
            🛡
          </span>
          <p className="text-latin text-dim">
            Nobody from our team will ever ask you for this code.
          </p>
        </div>
      </main>
    </Screen>
  );
}
