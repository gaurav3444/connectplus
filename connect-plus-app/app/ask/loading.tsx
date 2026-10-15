import { Screen } from "../ui";

// The loading state, shown while an answer is found. Words, not a bare
// spinner: say what is happening and that waiting is the right thing to do.
export default function Loading() {
  return (
    <Screen>
      <main role="status" className="flex flex-1 flex-col justify-center px-6 py-8 sm:px-10">
        <span aria-hidden="true" className="text-[2rem] text-accent motion-safe:animate-pulse">
          ⌕
        </span>
        <h1 className="mt-3 text-heading font-medium leading-tight">Finding an answer…</h1>
        <p className="mt-2 text-body text-dim">This takes a few seconds. Please wait.</p>
      </main>
    </Screen>
  );
}
