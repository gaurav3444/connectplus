"use client";

import { useState, useSyncExternalStore } from "react";

// Voice input, at the same weight as typing. Web Speech API: no dependency and
// no key. It fills the question box rather than submitting, so the senior can
// see what was heard before asking.

// Not in TypeScript's DOM lib yet; this is the slice we use.
type Recognition = {
  lang: string;
  interimResults: boolean;
  onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void;
  onend: () => void;
  start: () => void;
};
type Ctor = new () => Recognition;

const subscribe = () => () => {};
const getCtor = () => {
  const w = window as unknown as { SpeechRecognition?: Ctor; webkitSpeechRecognition?: Ctor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
};

// The app's language codes, as a voice engine wants them.
const VOICE: Record<string, string> = { zh: "zh-CN", vi: "vi-VN", en: "en-AU" };

export default function Speak({
  target,
  lang,
  className,
  compact,
}: {
  target: string;
  lang: string;
  className: string;
  compact?: boolean;
}) {
  const [listening, setListening] = useState(false);
  // null on the server and in browsers without speech (Firefox): no button,
  // rather than a button that does nothing
  const Ctor = useSyncExternalStore(subscribe, getCtor, () => null);
  if (!Ctor) return null;

  function listen() {
    const r = new Ctor!();
    r.lang = VOICE[lang] ?? "en-AU";
    r.interimResults = false;
    r.onresult = (e) => {
      const box = document.getElementById(target) as HTMLTextAreaElement | HTMLInputElement;
      box.value = e.results[0][0].transcript;
      box.focus();
    };
    r.onend = () => setListening(false);
    setListening(true);
    r.start();
  }

  return (
    <>
      <button
        type="button"
        onClick={listen}
        disabled={listening}
        aria-label="Speak your question"
        className={className}
      >
        <span aria-hidden="true" className="text-[1.4rem]">
          🎤
        </span>
        {!compact && <span aria-hidden="true">{listening ? "Listening" : "Speak"}</span>}
      </button>
      {/* the recording state is announced in words, never shown by colour alone */}
      <span aria-live="polite" className="sr-only">
        {listening ? "Listening. Say your question now." : ""}
      </span>
    </>
  );
}
