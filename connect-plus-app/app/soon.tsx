import Link from "next/link";
import { BackLink, HEADER, Screen } from "./ui";

// Placeholder for the screens after 2, so nothing on Home leads to a 404 while
// the rest of the flow is built. Delete each use as its real screen lands.
export function Soon({ title }: { title: string }) {
  return (
    <Screen>
      <header className={HEADER}>
        <BackLink href="/home" label="Go back to the home screen" />
      </header>
      <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">{title}</h1>
        <p className="mt-3 text-body text-dim">
          This part is not built yet. Use the back arrow to return.
        </p>
        <p className="mt-auto pt-8 text-latin text-faint">
          <Link href="/home" className="text-link hover:underline">
            Back to the home screen
          </Link>
        </p>
      </main>
    </Screen>
  );
}
