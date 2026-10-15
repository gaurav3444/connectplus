"use client";

import { useEffect } from "react";
import { BTN_PRIMARY, Screen } from "./ui";

// The error state. Plain words, never a code, and the blame where it belongs.
export default function ErrorState({ error, retry }: { error: Error; retry: () => void }) {
  useEffect(() => console.error(error), [error]);
  return (
    <Screen>
      <main className="flex flex-1 flex-col justify-center px-6 py-8 sm:px-10">
        <span aria-hidden="true" className="text-[2rem]">
          ⚠
        </span>
        <h1 role="alert" className="mt-3 text-heading font-medium leading-tight">
          Something went wrong
        </h1>
        <p className="mt-2 text-body text-dim">
          It was our fault, not yours. Nothing you did was lost.
        </p>
        <button type="button" onClick={retry} className={`${BTN_PRIMARY} mt-7 text-body`}>
          Try again
        </button>
      </main>
    </Screen>
  );
}
