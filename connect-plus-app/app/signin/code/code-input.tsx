"use client";

import { useId, useState, useSyncExternalStore } from "react";
import { FIELD } from "../ui";

// ponytail: one real input sitting over six read-only boxes, rather than six
// inputs wired together. Paste and the email/SMS autofill both work, there is
// no focus juggling to get wrong, and the caret cannot get stranded in box 4.
// Six separate inputs would need JS for auto-advance anyway.

const subscribe = () => () => {}; // never fires: the value only flips at hydration

const BOX =
  "flex h-[3.8rem] flex-1 items-center justify-center rounded-[0.5rem] " +
  "border-2 bg-surface text-[1.7rem] font-medium";

export default function CodeInput({ invalid }: { invalid?: boolean }) {
  const id = useId();
  const [code, setCode] = useState("");
  const [focused, setFocused] = useState(false);
  // Before hydration the boxes cannot fill in, so the input stays a plain
  // visible field — typing a code still works with JavaScript off. False on the
  // server, true once hydrated; useSyncExternalStore is how you ask that
  // without an effect.
  const live = useSyncExternalStore(subscribe, () => true, () => false);

  return (
    <>
      <label
        htmlFor={id}
        className={live ? "sr-only" : "mb-2 block text-body font-medium text-dim"}
      >
        The six numbers we sent you
      </label>
      <div className="relative">
        <input
          id={id}
          name="code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          required
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? "code-error" : undefined}
          className={
            live
              ? "absolute inset-0 h-full w-full cursor-pointer opacity-0"
              : `${FIELD} text-body tracking-[0.5em]`
          }
        />
        {live && (
          // decorative: the input above is what a screen reader and the form see
          <div aria-hidden="true" className="flex gap-2">
            {Array.from({ length: 6 }, (_, i) => {
              const filled = i < code.length;
              const next = focused && i === code.length;
              return (
                <div
                  key={i}
                  className={`${BOX} ${
                    filled || next ? "border-accent" : "border-line"
                  } ${filled ? "text-ink" : "text-faint"}`}
                >
                  {filled ? code[i] : "•"}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
