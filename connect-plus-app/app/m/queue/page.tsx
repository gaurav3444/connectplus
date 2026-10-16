import Link from "next/link";
import {
  describe,
  HELPER,
  helperPing,
  LANG_NAMES,
  minutes,
  sessionsOf,
  waiting,
} from "../../helpdesk";
import Poll from "../../poll";
import { join } from "../actions";

// Screen 4, the queue: who is waiting, in what language, stuck on what, and
// for how long. Requests this helper cannot take because of language stay in
// the list, greyed, so nobody waits invisibly.

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

export default async function Queue({ searchParams }: PageProps<"/m/queue">) {
  const { gone } = await searchParams;
  // having this screen open is what makes a helper available
  helperPing();
  const queue = waiting();
  const mine = sessionsOf(HELPER.name);

  return (
    <>
      <Poll />
      <header className="flex flex-wrap items-center gap-3 border-b border-line pb-4">
        <h1 className="text-[1.25rem] font-medium">Helper dashboard</h1>
        <span className="ml-auto flex items-center gap-2 rounded-full bg-tint px-3 py-1 text-[0.7rem] font-medium text-link">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-accent" />
          Available
        </span>
        <span className="text-[0.7rem] text-muted">
          {HELPER.name} · {HELPER.langs.join(", ").toUpperCase()}
        </span>
      </header>

      {gone && (
        <p role="status" className="mt-4 rounded-md bg-panel px-3 py-2 text-dim">
          That request was taken by another helper or cancelled.
        </p>
      )}

      {mine.length > 0 && (
        <section className="mt-5">
          <h2 className="font-medium">Your sessions</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {mine.map((r) => (
              <li key={r.id}>
                <Link
                  href={`/m/session/${r.id}`}
                  className={`inline-flex rounded-md border border-accent px-3 py-1.5 text-link hover:bg-tint ${FOCUS}`}
                >
                  Back to {r.senior}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-6">
        <h2 className="flex items-baseline gap-3">
          <span className="font-medium">Waiting for help</span>
          <span className="text-[0.7rem] text-muted">
            {queue.length} {queue.length === 1 ? "person" : "people"}
          </span>
        </h2>

        {queue.length === 0 ? (
          <p className="mt-4 rounded-md border border-dashed border-line p-6 text-center text-muted">
            Nobody is waiting right now. This list updates by itself.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[40rem] text-left">
              <thead className="bg-surface text-[0.65rem] uppercase tracking-wider text-muted">
                <tr>
                  {["Who", "Language", "Topic", "Tried", "Waiting", ""].map((h) => (
                    <th key={h} scope="col" className="px-3 py-2 font-medium">
                      {h || <span className="sr-only">Action</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {queue.map((r) => {
                  const d = describe(r);
                  const can = HELPER.langs.includes(r.lang);
                  return (
                    <tr key={r.id} className={`border-t border-line ${can ? "" : "text-faint"}`}>
                      <td className="px-3 py-2.5 font-medium">{r.senior}</td>
                      <td className="px-3 py-2.5">{LANG_NAMES[r.lang] ?? r.lang}</td>
                      <td className="px-3 py-2.5">{d.topic}</td>
                      <td className="px-3 py-2.5">{d.tried}</td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {minutes(r.created)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {can ? (
                          <form action={join}>
                            <input type="hidden" name="id" value={r.id} />
                            <button
                              type="submit"
                              className={`rounded-md border border-accent bg-fill px-3 py-1.5 font-medium text-on-fill hover:bg-fill-hover ${FOCUS}`}
                            >
                              Join<span className="sr-only"> {r.senior}</span>
                            </button>
                          </form>
                        ) : (
                          // a word, not just grey: say why it cannot be taken
                          <span className="whitespace-nowrap text-[0.7rem]">
                            Needs {r.lang.toUpperCase()}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-[0.7rem] text-muted">
          Requests you cannot take because of language are shown greyed, so nobody waits
          invisibly.
        </p>
      </section>
    </>
  );
}
