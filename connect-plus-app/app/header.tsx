import Link from "next/link";
import { cookies } from "next/headers";
import { CTRL, HEADER, HeaderControls } from "./ui";

// Apart from ui.tsx because it reads cookies: ui.tsx is also imported by the
// client-side code input, and next/headers cannot follow it there.

// The senior-facing header from Home onwards: language, text size, and a
// helper always one tap away — at a quieter weight than the screen's own
// primary action.
export async function AppHeader({ back, help = true }: { back: string; help?: boolean }) {
  const jar = await cookies();
  return (
    <header className={HEADER}>
      <HeaderControls
        lang={jar.get("lang")?.value ?? "en"}
        big={jar.get("text-size")?.value === "lg"}
        back={back}
      />
      {help && (
        <Link href="/help" className={`${CTRL} ml-auto whitespace-nowrap text-body`}>
          <span aria-hidden="true">🤝</span>
          I need help
        </Link>
      )}
    </header>
  );
}
