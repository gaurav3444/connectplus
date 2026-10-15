import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Screen 0. Language comes before login: a senior who reads no English must be
// able to get past this screen unaided. So: native script first and largest,
// no header, no nav, no logo, no flags (ambiguous for languages), one job.
const LANGS = [
  { code: "zh", lang: "zh", native: "中文", latin: "Chinese" },
  { code: "vi", lang: "vi", native: "Tiếng Việt", latin: "Vietnamese" },
  { code: "en", lang: "en", native: "English", latin: "English" },
];

async function pick(code: string) {
  "use server";
  // Cookie, not localStorage: readable server-side when i18n middleware lands.
  (await cookies()).set("lang", code, {
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
    sameSite: "lax",
  });
  redirect("/signin");
}

const TILE =
  "flex h-full min-h-[7rem] w-full flex-col items-center justify-center gap-1.5 " +
  "rounded-xl border-2 bg-surface px-2 py-4 text-ink transition-colors sm:min-h-[10rem] sm:px-4 " +
  "hover:border-accent focus-visible:outline-3 focus-visible:outline-offset-3 " +
  "focus-visible:outline-accent";

export default async function LanguageSelect() {
  const current = (await cookies()).get("lang")?.value;

  return (
    <div className="flex min-h-dvh justify-center bg-bg">
      {/* content is vertically centred and grows with the viewport — no phone-width
          column stranded on a laptop screen */}
      <main className="flex w-full max-w-3xl flex-col justify-center px-6 py-10 sm:px-10">
        {/* Heading in every language — an English-only heading defeats the screen */}
        <h1 className="text-heading font-medium leading-tight">
          <span lang="en">Choose your language</span>
        </h1>
        <p className="mt-1 text-body text-muted">
          <span lang="zh">选择您的语言</span>
          <span aria-hidden="true"> · </span>
          <span lang="vi">Chọn ngôn ngữ</span>
        </p>

        {/* one column under 375px — two would squeeze "Tiếng Việt" onto three lines */}
        {/* three across only from 1024px — narrower than that, three tiles are too
            tight for "Tiếng Việt" on one line */}
        <ul className="mt-8 grid grid-cols-1 gap-4 min-[375px]:grid-cols-2 lg:grid-cols-3 lg:gap-5">
          {LANGS.map((l) => {
            const selected = current === l.code;
            return (
              <li key={l.code}>
                {/* form + server action: works with JavaScript off, no client component */}
                <form action={pick.bind(null, l.code)} className="h-full">
                  <button
                    type="submit"
                    aria-current={selected ? "true" : undefined}
                    className={`${TILE} ${selected ? "border-accent" : "border-line"}`}
                  >
                    {/* lang attribute so a screen reader switches voice */}
                    <span lang={l.lang} className="text-native font-medium">
                      {l.native}
                    </span>
                    <span className="text-latin text-muted">
                      {/* tick, not colour alone, marks the current choice */}
                      {selected && <span aria-label="current">✓ </span>}
                      {l.latin}
                    </span>
                  </button>
                </form>
              </li>
            );
          })}
        </ul>

        <p className="mt-8 text-center text-latin text-muted">
          <span lang="en">You can change this at any time.</span>
          <span aria-hidden="true"> · </span>
          <span lang="zh">您可以随时更改。</span>
          <span aria-hidden="true"> · </span>
          <span lang="vi">Ông/bà có thể đổi bất cứ lúc nào.</span>
        </p>
      </main>
    </div>
  );
}
