import Link from "next/link";

// Shared chrome for screens 1 and 1b. Sizes are the mockup's (48px controls,
// 60px actions, 10px radius) expressed in rem so they grow with the A+ setting.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

export const CTRL =
  "flex min-h-[2.4rem] items-center justify-center gap-1.5 rounded-[0.5rem] border " +
  `border-line px-3 text-ink transition-colors hover:border-accent ${FOCUS}`;

export const FIELD =
  "min-h-[3rem] w-full rounded-[0.5rem] border-2 border-line bg-surface px-4 " +
  `text-ink placeholder:text-faint focus:border-accent ${FOCUS}`;

export const BTN_PRIMARY =
  "flex min-h-[3rem] w-full items-center justify-center gap-2 rounded-[0.5rem] " +
  "border-2 border-accent bg-fill px-4 font-semibold text-on-fill transition-colors " +
  `hover:bg-fill-hover ${FOCUS}`;

export const BTN_SECONDARY =
  "flex min-h-[3rem] w-full items-center justify-center gap-2 rounded-[0.5rem] " +
  "border-2 border-line px-4 font-medium text-ink transition-colors " +
  `hover:border-accent hover:text-accent ${FOCUS}`;

// An arrow glyph, not an icon font: two screens do not justify a dependency.
export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link href={href} aria-label={label} className={`${CTRL} w-[2.4rem] px-0`}>
      <span aria-hidden="true">←</span>
    </Link>
  );
}

export function Screen({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh justify-center bg-bg">
      {/* same growth rule as screen 0: a phone column is the floor, not the cap */}
      <div className="flex w-full max-w-2xl flex-col">{children}</div>
    </div>
  );
}
