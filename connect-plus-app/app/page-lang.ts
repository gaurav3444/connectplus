"use client";

import { useSyncExternalStore } from "react";
import { dict } from "./i18n";

// For the two screens that render in the browser (error, offline): the root
// layout has already put the chosen language on <html lang>, so read it from
// there. "zh-Hans" → "zh". English during server rendering and hydration.
const subscribe = () => () => {};
export function usePageDict() {
  const lang = useSyncExternalStore(
    subscribe,
    () => document.documentElement.lang.slice(0, 2),
    () => "en",
  );
  return dict(lang);
}
