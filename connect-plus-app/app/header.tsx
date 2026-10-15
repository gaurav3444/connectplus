import Link from "next/link";
import { cookies } from "next/headers";
import { dict } from "./i18n";
import { CTRL, HEADER, HeaderControls } from "./ui";

// Apart from ui.tsx because it reads cookies: ui.tsx is also imported by the
// client-side code input, and next/headers cannot follow it there.

// The senior-facing header from Home onwards: language, text size, and a
// helper always one tap away — at a quieter weight than the screen's own
// primary action.
export async function AppHeader({ back, help = true }: { back: string; help?: boolean }) {
  const jar = await cookies();
  const lang = jar.get("lang")?.value ?? "en";
  const t = dict(lang);
  return (
    <header className={HEADER}>
      {/* desktop only: on a phone the space goes to the controls */}
      <Link
        href="/home"
        className="mr-auto hidden min-h-[2.4rem] content-center text-body font-semibold tracking-tight lg:block"
      >
        CONNECT Plus
      </Link>
      <HeaderControls
        lang={lang}
        big={["lg", "xl"].includes(jar.get("text-size")?.value ?? "")}
        back={back}
        t={t}
      />
      {/* Settings sits in the header where there is room; on a phone it is a
          quiet link at the bottom of Home */}
      <Link href="/settings" className={`${CTRL} hidden text-body lg:flex`}>
        <span aria-hidden="true">⚙</span>
        {t.settings}
      </Link>
      {help && (
        <Link href="/help" className={`${CTRL} ml-auto whitespace-nowrap text-body lg:ml-0`}>
          <span aria-hidden="true">🤝</span>
          {t.needHelp}
        </Link>
      )}
    </header>
  );
}
