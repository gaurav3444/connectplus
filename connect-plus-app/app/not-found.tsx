import Link from "next/link";
import { BTN_PRIMARY, Screen } from "./ui";

// A wrong or old link. Say so plainly and give one way forward.
export default function NotFound() {
  return (
    <Screen>
      <main className="flex flex-1 flex-col justify-center px-6 py-8 sm:px-10">
        <h1 className="text-heading font-medium leading-tight">We could not find that page</h1>
        <p className="mt-2 text-body text-dim">
          The link may be old, or it may have a typing mistake. Nothing is broken.
        </p>
        <Link href="/home" className={`${BTN_PRIMARY} mt-7 text-body`}>
          Go to the home screen
        </Link>
      </main>
    </Screen>
  );
}
