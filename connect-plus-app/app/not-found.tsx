import Link from "next/link";
import { getT } from "./t";
import { BTN_PRIMARY, Screen } from "./ui";

// A wrong or old link. Say so plainly and give one way forward.
export default async function NotFound() {
  const t = await getT();
  return (
    <Screen>
      <main className="flex flex-1 flex-col justify-center px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">{t.notFoundTitle}</h1>
        <p className="mt-2 text-body text-dim">
          {t.notFoundBody}
        </p>
        <Link href="/home" className={`${BTN_PRIMARY} mt-7 text-body`}>
          {t.goHome}
        </Link>
      </main>
    </Screen>
  );
}
