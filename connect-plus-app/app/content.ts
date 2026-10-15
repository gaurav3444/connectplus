// The lesson tree for screen 3a: category → subcategory → resource. Device
// first at the top, tasks underneath, never more than seven to a level.
//
// ponytail: hard-coded until there is a content backend. Resources live in one
// map keyed by id so the same lesson can sit under two topics without being
// written twice.

// One screen each. `picture` is the alt text for the screenshot that will sit
// there — it describes where the button is, never just "screenshot".
export type Step = {
  title: string;
  body: string;
  picture?: string;
  // the hands-on step: the senior does it on a simulated screen
  practice?: boolean;
};

export type Resource = {
  id: string;
  title: string;
  steps: Step[];
};

export type Topic = {
  slug: string;
  title: string;
  icon: string;
  // a category holds topics, a subcategory holds resource ids
  topics?: Topic[];
  resources?: string[];
};

export const RESOURCES: Record<string, Resource> = {
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
        body: "On the practice phone below, tap the pencil in the top right corner. Nothing here can be sent or broken.",
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

export const CATEGORIES: Topic[] = [
  {
    slug: "phone",
    title: "Phone & Tablet",
    icon: "📱",
    topics: [
      { slug: "calls", title: "Calls", icon: "📞" },
      {
        slug: "messages",
        title: "Messages",
        icon: "💬",
        resources: ["send-text", "scam-text", "bigger-writing"],
      },
      { slug: "camera", title: "Camera & photos", icon: "📷" },
      { slug: "apps", title: "Apps", icon: "▦" },
      { slug: "settings", title: "Settings", icon: "⚙" },
      { slug: "wifi", title: "Wi-Fi", icon: "📶" },
    ],
  },
  { slug: "computer", title: "Computer", icon: "💻", topics: [] },
  {
    slug: "safety",
    title: "Staying Safe Online",
    icon: "🛡",
    topics: [
      { slug: "scams", title: "Scam texts and emails", icon: "⚠", resources: ["scam-text"] },
    ],
  },
  { slug: "government", title: "Government & Health", icon: "🏥", topics: [] },
  { slug: "family", title: "Talking to Family", icon: "👪", topics: [] },
  { slug: "money", title: "Money & Shopping", icon: "👛", topics: [] },
  { slug: "ai", title: "AI & New Technology", icon: "✨", topics: [] },
];

// Every resource id under a topic, at any depth — a category counts as
// visited once any lesson inside it has been read.
export function resourceIds(t: Topic): string[] {
  return [...(t.resources ?? []), ...(t.topics ?? []).flatMap(resourceIds)];
}

// The first subcategory holding a lesson, for its Back button and breadcrumb.
export function topicOf(id: string) {
  for (const c of CATEGORIES)
    for (const t of c.topics ?? [])
      if (t.resources?.includes(id)) return { href: `/browse/${c.slug}/${t.slug}`, title: t.title };
  return { href: "/browse", title: "Browse topics" };
}
