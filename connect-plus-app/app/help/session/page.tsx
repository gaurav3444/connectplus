import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Speak from "../../ask/speak";
import { AppHeader } from "../../header";
import { backTo, elapsed, getRequest, helperAvailable } from "../../helpdesk";
import { dict } from "../../i18n";
import Poll from "../../poll";
import { BTN_PRIMARY, BTN_SECONDARY, CTRL, HEADER, Screen } from "../../ui";
import { cancelHelp, endHelp, leaveHelp, notifyMe, sayToHelper } from "../actions";
import { Icon } from "../../icons";

// Screen 3d after consent: waiting, then the conversation. The waiting state
// says how long it has been instead of spinning forever, and the session keeps
// the senior's step in view beside the chat.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

export default async function HelpSession() {
  const jar = await cookies();
  const r = getRequest(jar.get("help")?.value);
  if (!r) redirect("/help");
  const lang = jar.get("lang")?.value ?? "en";
  const t = dict(lang);
  const back = backTo(r);

  if (r.ended) {
    return (
      <Screen>
        <AppHeader back="/help/session" help={false} />
        <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
          <h1 className="text-heading font-medium leading-tight">{t.sessionEnded}</h1>
          <p className="mt-3 text-body text-dim">
            {t.sessionEndedBody}
          </p>
          <form action={leaveHelp} className="mt-8">
            <button type="submit" className={`${BTN_PRIMARY} text-body`}>
              {r.lesson ? t.backToStep : t.back}
            </button>
          </form>
        </main>
      </Screen>
    );
  }

  if (!r.helper) {
    const free = helperAvailable();
    return (
      <Screen>
        <Poll />
        <AppHeader back="/help/session" help={false} />
        <main className="flex flex-1 flex-col px-6 py-8 sm:px-10">
          <span
            aria-hidden="true"
            className="grid h-[4rem] w-[4rem] place-items-center rounded-full bg-fill text-[1.8rem] text-on-fill"
          >
            <Icon name={free ? "hourglass" : "moon"} />
          </span>
          {free ? (
            <>
              <h1 className="mt-5 text-heading font-medium leading-tight">{t.looking}</h1>
              <p className="mt-3 text-body text-dim">
                {t.lookingBody}
              </p>
              <p role="status" className="mt-4 self-start rounded-full bg-panel px-4 py-1.5 text-latin text-dim">
                {t.waiting(elapsed(r.created))}
              </p>
              <p className="mt-6 text-body text-muted">
                {t.whileWait}
              </p>
            </>
          ) : (
            <>
              <h1 className="mt-5 text-heading font-medium leading-tight">{t.noHelper}</h1>
              <p className="mt-3 text-body text-dim">
                {t.noHelperBody}
              </p>
              {r.notify ? (
                <p className="mt-6 text-body text-link">
                  <Icon name="check" className="mr-[0.3em]" />
                  {t.willTell}
                </p>
              ) : (
                <form action={notifyMe} className="mt-6">
                  <button type="submit" className={`${BTN_PRIMARY} text-body`}>
                    {t.tellMe}
                  </button>
                </form>
              )}
            </>
          )}

          <div className="mt-auto flex flex-col gap-4 pt-8">
            <Link href={back} className={`${BTN_SECONDARY} text-body`}>
              {r.lesson ? t.backToStep : t.back}
            </Link>
            <form action={cancelHelp}>
              <button
                type="submit"
                className={`min-h-[2.8rem] w-full text-body font-medium text-link underline-offset-4 hover:underline ${FOCUS}`}
              >
                {t.cancelRequest}
              </button>
            </form>
          </div>
        </main>
      </Screen>
    );
  }


  return (
    <Screen>
      <Poll />
      <header className={HEADER}>
        <span
          aria-hidden="true"
          className="grid h-[2.4rem] w-[2.4rem] flex-none place-items-center rounded-full bg-fill font-medium text-on-fill"
        >
          {r.helper[0]}
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-body font-medium">{r.helper}</span>
          <span className="text-latin text-link">{t.helperHere}</span>
        </span>
        <form action={endHelp} className="ml-auto">
          <button type="submit" className={`${CTRL} text-body`}>
            {t.end}
          </button>
        </form>
      </header>

      {r.lesson && (
        <div className="flex items-center gap-3 bg-panel px-6 py-3 sm:px-10">
          <span className="flex-1 text-latin text-dim">
            {t.yourStep} <span className="text-ink">{r.lesson.stepTitle}</span>
          </span>
          <Link href={back} className="min-h-[2.4rem] content-center text-latin font-medium text-link underline underline-offset-4">
            {t.view}
          </Link>
        </div>
      )}

      <main className="flex flex-1 flex-col px-6 py-5 sm:px-10">
        {/* a log, so a screen reader hears each new message as it arrives */}
        <ol role="log" aria-label={t.conversation} className="flex flex-1 flex-col gap-3">
          {r.messages.length === 0 && (
            <li className="text-body text-muted">
              {t.helperJoined(r.helper)}
            </li>
          )}
          {r.messages.map((m, i) => (
            <li
              key={i}
              className={`max-w-[85%] rounded-[0.8rem] px-4 py-3 text-body ${
                m.from === "senior"
                  ? "self-end rounded-br-[0.2rem] bg-fill text-on-fill"
                  : "self-start rounded-bl-[0.2rem] bg-surface"
              }`}
            >
              <span className="sr-only">{m.from === "senior" ? t.you : r.helper}: </span>
              {m.text}
            </li>
          ))}
        </ol>

        <form action={sayToHelper} className="mt-5 flex gap-3">
          <label htmlFor="say" className="sr-only">
            {t.writeMessage}
          </label>
          <input
            id="say"
            name="text"
            required
            autoComplete="off"
            placeholder={t.writeMessagePlaceholder}
            className={`min-h-[2.8rem] w-full rounded-[0.6rem] border-2 border-line bg-surface px-4 text-body text-ink placeholder:text-faint focus:border-accent ${FOCUS}`}
          />
          <Speak
            target="say"
            lang={lang}
            labels={t.speak}
            compact
            className={`flex w-[2.8rem] flex-none items-center justify-center rounded-[0.6rem] border-2 border-line hover:border-accent disabled:border-accent ${FOCUS}`}
          />
          <button type="submit" className={`${BTN_PRIMARY.replace("w-full", "")} flex-none text-body`}>
            {t.send}
          </button>
        </form>
      </main>
    </Screen>
  );
}
