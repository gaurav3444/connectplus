// The lesson tree for screens 3a and 3c: category → subcategory → resource.
// Device first at the top, tasks underneath, never more than seven to a level.
//
// The real tree comes from connectplus-rag: `python -m rag.main browse
// --build` snapshots it into the browse_resources table in its Supabase
// database, built only from pages of approved sites already in the index.
// Each resource is a section of one of those sites, and its pages are the
// steps. With no Supabase configured, the sample lessons below stand in.
//
// Resources live in one map keyed by id, so the same lesson can sit under two
// topics without being written twice.

import type { IconName } from "./icons";

// One screen each. `picture` is the alt text for the screenshot that will sit
// there — it describes where the button is, never just "screenshot".
export type Step = {
  title: string;
  // empty for a step that is a page on an approved site: `url` is the content
  body: string;
  url?: string;
  picture?: string;
  // the hands-on step: the senior does it on a simulated screen
  practice?: boolean;
};

export type Resource = {
  id: string;
  title: string;
  // the approved site the steps live on, for steps that are its pages
  domain?: string;
  steps: Step[];
};

export type Catalogue = { categories: Topic[]; resources: Record<string, Resource> };

export type Topic = {
  slug: string;
  title: string;
  icon?: IconName;
  // a category holds topics, a subcategory holds resource ids
  topics?: Topic[];
  resources?: string[];
};

const RESOURCES: Record<string, Resource> = {
  "send-text": {
    id: "send-text",
    title: "Sending a text message",
    steps: [
      {
        title: "Open Messages",
        body: "Find the green square with a white speech bubble on your home screen. Tap it once.",
        picture: "Phone home screen. The Messages app, a green square with a white speech bubble, is circled.",
      },
      {
        title: "Tap the pencil to start a new message",
        body: "It sits in the top right corner of the Messages screen. It may look like a small square with a pencil in it.",
        picture: "Messages app. The compose button, a square with a pencil, is circled in the top right corner.",
      },
      {
        title: "Now you try it",
        body: "On the practice phone, tap the pencil in the top right corner. Nothing here can be sent or broken.",
        practice: true,
      },
      {
        title: "Choose who to send it to",
        body: "Type the person’s name in the To box at the top. When their name appears underneath, tap it.",
        picture: "New message screen. The To box at the top is circled, with a name suggested below it.",
      },
      {
        title: "Write your message and send it",
        body: "Tap the long box at the bottom and type your message. Then tap the arrow next to it to send.",
        picture: "New message screen. The typing box at the bottom and the send arrow beside it are circled.",
      },
    ],
  },
  "scam-text": {
    id: "scam-text",
    title: "Is this message a scam?",
    steps: [
      {
        title: "Does it rush you?",
        body: "Scam messages say you must act now, or your account will close. A real company gives you time.",
      },
      {
        title: "Do you know the sender?",
        body: "Look at who sent it. A number you do not know, pretending to be your bank or the post office, is a warning sign.",
      },
      {
        title: "Look closely at the link",
        body: "Scam links look almost right, but not quite. Do not tap the link. Go to the real website or app yourself instead.",
      },
      {
        title: "Never share a password or a code",
        body: "Real banks and government services never ask for these in a message. If a message asks, it is a scam. Delete it.",
      },
    ],
  },
  "bigger-writing": {
    id: "bigger-writing",
    title: "Making the writing bigger",
    steps: [
      {
        title: "Open Settings",
        body: "Find the grey gear on your home screen and tap it.",
        picture: "Phone home screen. The Settings app, a grey gear, is circled.",
      },
      {
        title: "Tap Display",
        body: "Scroll down until you see Display. On an iPhone it is called Display & Brightness. Tap it.",
        picture: "Settings list. The Display option is circled.",
      },
      {
        title: "Move the slider",
        body: "Tap Text size, or Font size. Move the slider to the right until the writing is easy to read.",
        picture: "Text size screen. The slider is circled, with an arrow pointing right.",
      },
    ],
  },
};

const CATEGORIES: Topic[] = [
  {
    slug: "phone",
    title: "Phone & Tablet",
    icon: "smartphone",
    topics: [
      { slug: "calls", title: "Calls", icon: "phone" },
      {
        slug: "messages",
        title: "Messages",
        icon: "message-circle",
        resources: ["send-text", "scam-text", "bigger-writing"],
      },
      { slug: "camera", title: "Camera & photos", icon: "camera" },
      { slug: "apps", title: "Apps", icon: "layout-grid" },
      { slug: "settings", title: "Settings", icon: "settings" },
      { slug: "wifi", title: "Wi-Fi", icon: "wifi" },
    ],
  },
  { slug: "computer", title: "Computer", icon: "laptop", topics: [] },
  {
    slug: "safety",
    title: "Staying Safe Online",
    icon: "shield",
    topics: [
      { slug: "scams", title: "Scam texts and emails", icon: "triangle-alert", resources: ["scam-text"] },
    ],
  },
  { slug: "government", title: "Government & Health", icon: "hospital", topics: [] },
  { slug: "family", title: "Talking to Family", icon: "users", topics: [] },
  { slug: "money", title: "Money & Shopping", icon: "wallet", topics: [] },
  { slug: "ai", title: "AI & New Technology", icon: "sparkles", topics: [] },
];

// Every resource id under a topic, at any depth — a category counts as
// visited once any lesson inside it has been read.
export function resourceIds(t: Topic): string[] {
  return [...(t.resources ?? []), ...(t.topics ?? []).flatMap(resourceIds)];
}

// The first subcategory holding a lesson, for its Back button and breadcrumb.
export function topicOf(cats: Topic[], id: string) {
  for (const c of cats)
    for (const t of c.topics ?? [])
      if (t.resources?.includes(id)) return { href: `/browse/${c.slug}/${t.slug}`, title: t.title };
  return { href: "/browse", title: "Browse topics" };
}

// ---- from connectplus-rag ----------------------------------------------

// The same Supabase database connectplus-rag indexes into. Server-side only:
// this module never reaches the browser, and neither does the URL.
const DB = process.env.DATABASE_URL;
const TTL = 10 * 60_000; // the table only changes when rag re-indexes

// globalThis so dev-mode reloads reuse one pool and one cached copy
const g = globalThis as unknown as {
  browsePool?: import("pg").Pool;
  browseCache?: { at: number; data: Catalogue };
};

export async function catalogue(): Promise<Catalogue> {
  if (!DB) return { categories: CATEGORIES, resources: RESOURCES };
  if (g.browseCache && Date.now() - g.browseCache.at < TTL) return g.browseCache.data;

  if (!g.browsePool) {
    const { Pool } = await import("pg");
    g.browsePool = new Pool({
      connectionString: DB,
      max: 2,
      connectionTimeoutMillis: 15_000,
      // ponytail: encrypted but not verified — Supabase signs with its own
      // CA, which Node does not trust. Same as rag's psycopg2 default
      // (sslmode=prefer). To verify, download the CA from Supabase ->
      // Database -> SSL and pass it as ssl: { ca }.
      ssl: { rejectUnauthorized: false },
    });
  }
  // Read-only by statement; a failed read throws to the error screen, not
  // an empty menu — "nothing here" would be untrue.
  const { rows } = await g.browsePool.query<Row>(
    "select * from browse_resources order by category_pos, subcategory_pos, resource_pos",
  );
  const data = fromRows(rows);
  g.browseCache = { at: Date.now(), data };
  return data;
}

export async function getResource(id: string) {
  return (await catalogue()).resources[id];
}

// One row per resource, as `browse --build` writes it (rag/config/schema.sql).
export type Row = {
  category_id: string;
  category_title: string;
  category_pos: number;
  subcategory_id: string;
  subcategory_title: string;
  subcategory_pos: number;
  resource_pos: number;
  resource_id: string; // 'domain/path' of the site section
  url: string;
  domain: string;
  title: string;
  pages: { doc_id: string; url: string; title: string }[]; // landing page first
};

// rag's category ids, given the icons the design puts beside them
const ICONS: Record<string, IconName> = {
  "phone-tablet": "smartphone",
  computer: "laptop",
  "staying-safe": "shield",
  "government-health": "hospital",
  "talking-to-family": "users",
  "money-shopping": "wallet",
  "ai-new-tech": "sparkles",
};

// A subcategory with no resources has no rows, so it does not appear: the
// tree is only ever what the index can actually teach.
export function fromRows(rows: Row[]): Catalogue {
  const categories: Topic[] = [];
  const resources: Record<string, Resource> = {};
  const sorted = [...rows].sort(
    (a, b) =>
      a.category_pos - b.category_pos ||
      a.subcategory_pos - b.subcategory_pos ||
      a.resource_pos - b.resource_pos,
  );
  for (const r of sorted) {
    let cat = categories.find((c) => c.slug === r.category_id);
    if (!cat) {
      cat = { slug: r.category_id, title: r.category_title, icon: ICONS[r.category_id], topics: [] };
      categories.push(cat);
    }
    let sub = cat.topics!.find((t) => t.slug === r.subcategory_id);
    if (!sub) {
      sub = { slug: r.subcategory_id, title: r.subcategory_title, resources: [] };
      cat.topics!.push(sub);
    }
    // 'domain/path' has slashes; base64url makes it one URL segment
    const id = Buffer.from(r.resource_id).toString("base64url");
    if (!sub.resources!.includes(id)) sub.resources!.push(id);
    resources[id] ??= {
      id,
      title: r.title,
      domain: r.domain,
      steps: r.pages.map((p) => ({ title: p.title, body: "", url: p.url })),
    };
  }
  return { categories, resources };
}
