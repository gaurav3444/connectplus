# connect-plus-app

Responsive web frontend for **CONNECT Plus**, a digital navigation and referral platform for culturally and linguistically diverse (CALD) seniors.

Two user groups in one app: **seniors** looking for trusted help with an everyday digital task, and **volunteer mentors** who step in when a senior gets stuck. Talks to [`connectplus-llm`](../connectplus-llm) for answers and to Supabase for auth, data and realtime chat.

---

## Why this exists

CONNECT Plus is a trusted navigation layer, not another content repository. A senior starts with a real problem (*"I got a text saying my parcel is held, is it real?"*) and the platform helps them name the need, gives plain guidance with a visible source, and offers a human when that's the right answer.

Accessibility is not a pass at the end here; it **is** the design. Bolt it on later and you rebuild the app. Three rules drive the whole interface:

- **Language before login.** A Mandarin-speaking senior facing an English sign-in screen is blocked at step one. Screen 0 is a language grid in native script, so no English is required to get past it.
- **Provenance is visible, always.** Every answer shows the source site with a link out. That's the trust mechanism; a footnote doesn't do the job.
- **Mentor help is offered, not advertised.** A quiet persistent "I need help" button, plus a *prominent* proactive offer after several failed attempts or a long stall. Making it a third equal card on Home invites bypassing the learning entirely, which the client agreed to avoid.

## Screens

```
[0] Language select ─► [1] Sign in ─► [2] Home: "What would you like to do?"
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
              [3a] Browse topics                        [3b] Ask a question
              category → subcategory → resource         text or voice
                     │                                         │
                     └────────► [3c] Resource + practice ◄─────┘
                                         │
                                  "I'm stuck" ─► [3d] Mentor request ─► session
```

Persistent in the header everywhere: language switcher, text-size control (A / A / A), and a quiet **I need help**.

| Route | Screen | Notes |
|---|---|---|
| `/` | Language select | Native script first and largest (`中文`), Latin name below. No header, no nav, one job |
| `/signin` | Sign in | Magic-link or a large 6-digit code. **"Look around first"** path, since browsing needs no account |
| `/home` | Home | Two large cards: *Browse topics* · *Ask a question* |
| `/topics/[...path]` | Browse | Three levels, ≤7 cards per level, breadcrumb + big Back on every one |
| `/ask` | Ask | Large input + microphone, suggested question chips, streamed answer + source card |
| `/resource/[id]` | Resource + practice | One step per screen, guided practice walkthrough, persistent "I'm stuck" |
| `/mentor` | Mentor request | Consent screen showing exactly what will be shared, then waiting state |
| `/m/queue` | Mentor queue | Who, language, topic, waiting time |
| `/m/session/[id]` | Mentor session | Chat + senior context panel + guidance callout |
| `/settings` | Settings | Language, text size, high contrast, sign out |

Mentors are young volunteers on phones, so denser, faster, conventional UI is correct for `/m/*`. The senior-facing screens are the ones with the strict constraints.

## Design system

Non-negotiables, encoded as Tailwind tokens in `tailwind.config.ts`:

- **Type.** Base **20px** (not 16). Body 20-22px, headings 32-40px, buttons 22px semibold. Line height 1.6, max ~65 characters per line. Nothing under 18px anywhere, including legal text and captions.
- **Touch targets.** **56px** minimum, 16px minimum gap between adjacent targets. WCAG's 44px is a floor, not the target for this cohort.
- **Colour.** Aim **7:1** on body text, not the 4.5:1 minimum. Ageing eyes discriminate blues and purples poorly, so never encode meaning in blue-vs-purple, and never rely on colour alone; always pair with an icon or a text label. No light grey on white.
- **Buttons.** Filled, high contrast, text labels always. Icon-only is allowed for the back arrow and the microphone, nothing else. One obvious primary action per screen.
- **Layout.** Single column on mobile, at most two on desktop. No horizontal scroll at 320px. Everything survives 200% zoom without clipping.
- **Motion.** Minimal, respects `prefers-reduced-motion`. No carousels, no timed dismissals, no timeouts anywhere.

States that must be designed and built explicitly, because they get skipped and then hurt: **loading · empty · error · offline · no-answer-found · mentor-unavailable**. Errors are plain language in the user's language, never a code.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | Next.js (App Router) + TypeScript | One codebase, responsive, good a11y tooling |
| Styling | Tailwind | Design tokens live in config, so the type scale and target sizes are enforced not remembered |
| i18n | `next-intl` | Translated strings out of the code and reviewable by a native speaker |
| Auth + DB | Supabase | Postgres, auth, and realtime in one free service |
| Chat | Supabase Realtime | Already there; no second websocket layer |
| Voice input | Web Speech API | Native browser feature, no dependency and no key |
| Answers | `connectplus-llm` `/ask` over SSE | Streaming via `EventSource` |
| Tests | Playwright + `@axe-core/playwright` | Enough for a prototype |

## Setup

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

Requires Node 20+, and `connectplus-llm` running on port 8000 for answers.

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=       # anon key only; RLS does the enforcement
LLM_API_URL=http://localhost:8000
```

No service key and no LLM provider key in this repo. The anon key is safe in the bundle **only because** row-level security is enforced in the database.

## Roles and safety

- Role separation (`senior` / `mentor`) is enforced by **RLS in Postgres**, not by hiding UI. A mentor sees only the seniors they are actively helping.
- The **attempt counter lives in the database**, not in component state. The mentor-unlock rule depends on it, and it must hold across a refresh or a second device.
- The unlock threshold is checked **server-side**. The client only decides when to show the offer.
- Mentor guidance panel is visible for the whole session, not buried in onboarding, including the explicit rule that a mentor never asks for a password or a code.
- Consent before sharing: the senior sees what a mentor will be shown before they request help.

## Testing

```bash
npm run test:a11y     # axe-core across every route
npm run test:e2e      # the three senior paths end to end
```

Automated tools catch roughly a third of real WCAG issues, so the manual passes are the actual test:

- Both journeys **keyboard only**, no mouse.
- Both journeys with **NVDA or VoiceOver**.
- Every screen at **200% zoom** and at **320px** width.
- Open it on a real phone over the local network and confirm citation links reach the live source page.

Then the two checks worth more than any review:

- **Test the language screen alone** with someone who reads no English. If they can't get past it unaided, nothing after it matters.
- **One moderated session with a CALD senior**: pick a topic, reach a resource, reach the practice step. Watch where they stop.

Translations get a native-speaker review before any user session. Machine-translated safety advice is a risk, not a placeholder.

## Status

Prototype for CW2 (Digital Literacy Platform for CALD Seniors). Runs locally; no deployment or CI in scope.

Launch scope is English + Mandarin, 4-5 approved domains, one guided practice flow, mentor request plus a basic mentor view. The senior journey is built end to end first; the mentor layer is deliberately second, and is the most cuttable feature if time runs out. Accessibility, citations and safety guardrails are not cuttable, because without them this is a worse eSafety.
