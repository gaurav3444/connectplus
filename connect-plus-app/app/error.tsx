"use client";

import { useEffect } from "react";
import { usePageDict } from "./page-lang";
import { BTN_PRIMARY, Screen } from "./ui";
import { Icon } from "./icons";

// The error state. Plain words, never a code, and the blame where it belongs.
export default function ErrorState({ error, retry }: { error: Error; retry: () => void }) {
  useEffect(() => console.error(error), [error]);
  const t = usePageDict();
  return (
    <Screen>
      <main className="flex flex-1 flex-col justify-center px-6 py-8 sm:px-10">
        <span aria-hidden="true" className="text-[2rem]">
          <Icon name="triangle-alert" />
        </span>
        <h1 role="alert" className="mt-3 text-heading font-medium leading-tight">
          {t.errorTitle}
        </h1>
        <p className="mt-2 text-body text-dim">
          {t.errorBody}
        </p>
        <button type="button" onClick={retry} className={`${BTN_PRIMARY} mt-7 text-body`}>
          {t.tryAgain}
        </button>
      </main>
    </Screen>
  );
}
