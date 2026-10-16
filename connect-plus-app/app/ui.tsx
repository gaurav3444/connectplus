import Link from "next/link";

import { toggleTextSize } from "./actions";
import { LANG_LABEL, type Dict } from "./i18n";
import { Icon } from "./icons";

// Shared chrome for every senior screen. Sizes are the mockup's (48px controls,
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
      <Icon name="arrow-left" />
    </Link>
  );
}

// Phones get one column. From 1024px (lg) the header becomes a full-width
// bar and the screen's content is centred: `wide` screens (Home, Browse, an
// answer, a lesson) open up to 72rem for two columns, single-task screens
// (sign in, settings, help) stay a comfortable reading column.
//
// Written as child selectors so every page keeps its header + main shape:
// the header's padding lines its contents up with the wide content edge.
export function Screen({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div
      className={
        "flex min-h-dvh flex-col bg-bg " +
        "[&>header]:px-6 sm:[&>header]:px-10 lg:[&>header]:px-[max(2.5rem,calc(50%-33.5rem))] " +
        "[&>*:not(header)]:mx-auto [&>*:not(header)]:w-full [&>*:not(header)]:max-w-2xl " +
        (wide ? "lg:[&>*:not(header)]:max-w-6xl" : "")
      }
    >
      {children}
    </div>
  );
}

// Language and text size, in that focus order, on every screen with a header.
// Both are settings a senior may need *before* they can read the page, so
// neither is behind a menu.
export function HeaderControls({
  lang,
  big,
  back,
  t,
}: {
  lang: string;
  big: boolean;
  back: string;
  t: Dict;
}) {
  return (
    <>
      <Link href="/" className={`${CTRL} text-body`}>
        <Icon name="globe" />
        <span className="uppercase lg:hidden">{lang}</span>
        <span lang={lang} className="hidden lg:inline">
          {LANG_LABEL[lang] ?? lang}
        </span>
        <span className="sr-only">{t.changeLang}</span>
      </Link>
      <form action={toggleTextSize}>
        <input type="hidden" name="back" value={back} />
        <button type="submit" aria-pressed={big} className={`${CTRL} text-body`}>
          <span aria-hidden="true">
            A<sup className="text-[0.6em]">+</sup>
          </span>
          <span className="sr-only">
            {big ? t.textNormal : t.textBigger}
          </span>
        </button>
      </form>
    </>
  );
}

export const HEADER =
  "flex items-center gap-2 px-6 py-4 shadow-[0_1px_0_var(--color-line)] sm:px-10 lg:gap-3";

// The big, worded Back for screens a senior can get lost in. The breadcrumb
// says where you are; this is the 56px target that gets you out — breadcrumb
// text alone is too small to tap.
export function BackButton({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={
        "flex min-h-[2.8rem] items-center gap-2.5 self-start rounded-[0.5rem] border-2 " +
        "border-line pr-4 pl-3 text-body font-medium text-ink transition-colors " +
        `hover:border-accent hover:text-accent ${FOCUS}`
      }
    >
      <Icon name="arrow-left" />
      {children}
    </Link>
  );
}
