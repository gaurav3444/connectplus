"use client";

import { useSyncExternalStore } from "react";
import { usePageDict } from "./page-lang";
import { Icon } from "./icons";

// The offline state, as a banner over whatever screen is open — the screen
// itself stays readable. No timer: it goes when the connection comes back.
//
// ponytail: no service worker, so nothing is saved for offline reading yet
// and the banner does not promise it. Add one before showing "See what I
// saved" from the mockup.

const subscribe = (cb: () => void) => {
  addEventListener("online", cb);
  addEventListener("offline", cb);
  return () => {
    removeEventListener("online", cb);
    removeEventListener("offline", cb);
  };
};

export default function Offline() {
  const offline = useSyncExternalStore(subscribe, () => !navigator.onLine, () => false);
  const t = usePageDict();
  if (!offline) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-0 z-50 border-t-2 border-accent bg-surface px-6 py-4 text-body"
    >
      <p className="mx-auto max-w-2xl">
        <span className="font-medium">
          <Icon name="wifi" className="mr-[0.3em]" />
          {t.offline}
        </span>{" "}
        <span className="text-dim">
          {t.offlineBody}
        </span>
      </p>
    </div>
  );
}
