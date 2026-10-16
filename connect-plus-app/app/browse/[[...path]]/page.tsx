import Link from "next/link";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { catalogue, resourceIds, type Topic } from "../../content";
import { AppHeader } from "../../header";
import { getT } from "../../t";
import { BackButton, BTN_SECONDARY, Screen } from "../../ui";

// Screen 3a. One route for all three levels — /browse, /browse/phone,
// /browse/phone/messages — so the breadcrumb is just the URL read back.
// Getting lost with no way back is this cohort's most common failure, so every
// level carries both a breadcrumb and a big worded Back.

const FOCUS =
  "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-accent";

const TILE =
  "flex min-h-[3.6rem] items-center gap-4 rounded-[0.6rem] border-2 border-line bg-surface " +
  `px-4 py-3 text-ink transition-colors hover:border-accent lg:min-h-[4.4rem] lg:px-6 ${FOCUS}`;

const CARD =
  "flex flex-col items-start gap-2 rounded-[0.6rem] border-2 bg-surface p-4 text-ink " +
  `transition-colors ${FOCUS}`;

export default async function Browse({ params }: PageProps<"/browse/[[...path]]">) {
  const [{ path = [] }, jar, { categories, resources: all }, t] = await Promise.all([
    params,
    cookies(),
    catalogue(),
    getT(),
  ]);
  if (path.length > 2) notFound();

  const cat = path[0] ? categories.find((c) => c.slug === path[0]) : undefined;
  const sub = path[1] ? cat?.topics?.find((x) => x.slug === path[1]) : undefined;
  if ((path[0] && !cat) || (path[1] && !sub)) notFound();

  // Written by the resource screen when a lesson is finished.
  const read = new Set(jar.get("read")?.value.split(",") ?? []);

  const here = sub ?? cat;
  const title = here?.title ?? t.browse;
  const trail = [
    { href: "/home", label: t.home },
    { href: "/browse", label: t.browse },
    ...(cat ? [{ href: `/browse/${cat.slug}`, label: cat.title }] : []),
    ...(sub ? [{ href: `/browse/${cat!.slug}/${sub.slug}`, label: sub.title }] : []),
  ];
  const up = trail[trail.length - 2];

  const topics = sub ? undefined : (cat?.topics ?? categories);
  const resources = sub?.resources?.map((id) => all[id]);
  const empty = topics ? topics.length === 0 : !resources?.length;
  // the first lesson not yet read is the one obvious next step
  const next = resources?.find((r) => !read.has(r.id));

  return (
    <Screen wide>
      <AppHeader back={trail[trail.length - 1].href} />

      <main className="flex flex-1 flex-col px-6 py-6 sm:px-10">
        {/* side by side where there is room, as in the mockup's desktop Browse */}
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:gap-6">
          <BackButton href={up.href}>{t.backTo(up.label)}</BackButton>

          <nav aria-label={t.breadcrumb} className="text-latin text-muted">
            <ol className="flex flex-wrap gap-x-2">
              {trail.map((crumb, i) => {
                const last = i === trail.length - 1;
                return (
                  <li key={crumb.href} className="flex gap-2">
                    {last ? (
                      <span aria-current="page">{crumb.label}</span>
                    ) : (
                      <>
                        <Link href={crumb.href} className="hover:text-accent hover:underline">
                          {crumb.label}
                        </Link>
                        <span aria-hidden="true">›</span>
                      </>
                    )}
                  </li>
                );
              })}
            </ol>
          </nav>
        </div>

        <h1 className="mt-2 text-heading font-medium leading-tight lg:mt-6">{title}</h1>
        {cat && !sub && !empty && (
          <p className="mt-1 text-body text-dim">{t.learnAbout}</p>
        )}

        {empty ? (
          <div className="mt-8 flex flex-col gap-3">
            <h2 className="text-body font-medium">{t.emptyTitle}</h2>
            <p className="text-body text-dim">{t.emptyBody}</p>
            <Link href={up.href} className={`${BTN_SECONDARY} mt-2 text-body`}>
              {t.chooseAnother}
            </Link>
          </div>
        ) : topics ? (
          // one per row on a phone, two at most on a wide screen
          <ul className="mt-6 grid gap-3 sm:grid-cols-2 sm:gap-4 lg:gap-5">
            {topics.map((topic) => (
              <li key={topic.slug}>
                <TopicTile
                  topic={topic}
                  href={cat ? `/browse/${cat.slug}/${topic.slug}` : `/browse/${topic.slug}`}
                  visited={resourceIds(topic).some((id) => read.has(id))}
                  label={t.visited}
                />
              </li>
            ))}
          </ul>
        ) : (
          <ul className="mt-6 grid gap-4 lg:grid-cols-2 lg:gap-5">
            {resources!.map((r) => {
              const done = read.has(r.id);
              const start = r === next;
              return (
                <li key={r.id}>
                  <Link
                    href={`/resource/${r.id}`}
                    className={`${CARD} ${
                      start
                        ? "border-accent hover:bg-tint"
                        : "border-line hover:border-accent"
                    }`}
                  >
                    <span className="text-body font-medium">{r.title}</span>
                    {/* which approved site it comes from — provenance on the
                        menu too, not only on answers */}
                    {r.domain && <span className="text-latin text-muted">{t.from(r.domain)}</span>}
                    <span className="text-latin text-dim">
                      {t.steps(r.steps.length)}
                      {r.steps.some((st) => st.practice) ? t.withPractice : ""}
                    </span>
                    {/* a word and a mark, never colour alone */}
                    {start && (
                      <span className="text-latin font-medium text-link">
                        <span aria-hidden="true">▶ </span>
                        {t.startHere}
                      </span>
                    )}
                    {done && (
                      <span className="text-latin font-medium text-link">
                        <span aria-hidden="true">✓ </span>
                        {t.haveRead}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </main>
    </Screen>
  );
}

function TopicTile({
  topic,
  href,
  visited,
  label,
}: {
  topic: Topic;
  href: string;
  visited: boolean;
  label: string;
}) {
  return (
    <Link href={href} className={TILE}>
      {topic.icon && (
        <span aria-hidden="true" className="w-[1.6rem] flex-none text-center text-[1.4rem] text-accent">
          {topic.icon}
        </span>
      )}
      <span className="flex-1 text-body font-medium">{topic.title}</span>
      {visited ? (
        <span className="flex flex-none items-center gap-1 text-latin font-medium text-link">
          <span aria-hidden="true">✓</span>
          {label}
        </span>
      ) : (
        <span aria-hidden="true" className="flex-none text-body text-faint">
          ›
        </span>
      )}
    </Link>
  );
}
