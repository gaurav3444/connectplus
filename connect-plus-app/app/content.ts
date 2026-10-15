// The lesson tree for screen 3a: category → subcategory → resource. Device
// first at the top, tasks underneath, never more than seven to a level.
//
// ponytail: hard-coded until there is a content backend. Resources live in one
// map keyed by id so the same lesson can sit under two topics without being
// written twice.

export type Resource = {
  id: string;
  title: string;
  steps: number;
  practice?: boolean;
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
  "send-text": { id: "send-text", title: "How to send a text message", steps: 5, practice: true },
  "scam-text": { id: "scam-text", title: "Is this message a scam?", steps: 4 },
  "bigger-writing": { id: "bigger-writing", title: "Making the writing bigger", steps: 3 },
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
