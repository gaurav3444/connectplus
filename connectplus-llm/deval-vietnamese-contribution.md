# Vietnamese Language Layer — Scope of Work

**Owner:** Deval Patel
**Project:** CONNECT Plus (CW2) — Digital Literacy Platform for CALD Seniors
**Repo:** `connectplus-llm` (stages 07–10)
**Date:** 2 September 2026

---

## 1. Where this fits

The `connectplus-llm` service already defines the pipeline: detect language → rewrite the query into English → retrieve from `connectplus-rag` → generate an answer **in the senior's own language** → verify → stream.

That pipeline is language-agnostic. It has no idea whether Vietnamese comes out well or badly. **That gap is my scope.**

```
                    Vietnamese senior asks
                             │
   ┌─────────────────────────▼──────────────────────────┐
   │ connectplus-llm  (colleague's pipeline)            │
   │                                                    │
   │ [1] detect language      ◄── MY WORK: vi detection │
   │ [2] rewrite query → EN   ◄── MY WORK: vi rewriting │
   │                                                    │
   │     rag.retrieve(q_en, "vi")                       │
   │                                                    │
   │ [3] build prompt         ◄── MY WORK: vi register  │
   │ [4] generate in vi       ◄── MY WORK: model choice │
   │                                                    │
   │     rag.verify(draft, chunks)                      │
   │                                                    │
   │ [5] stream / refuse      ◄── MY WORK: vi refusal   │
   └─────────────────────────┬──────────────────────────┘
                             │
                   MY WORK: does it actually
                   read well to a Vietnamese
                   senior?  (eval + human check)
```

I am not rebuilding the pipeline. I am making one language work properly inside it, and producing the evidence that says so.

---

## 2. What is realistic, and what is not

| Idea | Realistic? | Why |
|---|---|---|
| Pre-train a Vietnamese LLM | ❌ No | Millions of dollars, months of compute. Not a semester project. |
| Build a Vietnamese translation model | ❌ No | The pipeline already translates with the LLM in the rewrite call. Rebuilding it adds risk, not marks. |
| **Vietnamese eval set + scoring** | ✅ Yes | Cheapest, highest-value. This is the evidence in the report. |
| **Vietnamese query rewriting + term expansion** | ✅ Yes | Prompt and fixture work. No new infrastructure. |
| **Vietnamese register / style rules in the prompt** | ✅ Yes | A template file plus a termbase. Large quality gain for small effort. |
| **Model bake-off for Vietnamese** | ✅ Yes | Run the same 20 questions across providers, score, pick one. This is the defensible "model selection" contribution. |
| LoRA fine-tune of a small model on Vietnamese plain-language QA | ⚠️ Stretch | Doable on Colab free tier, but only attempt once everything above is done. |

---

## 3. Deliverables, in priority order

### D1 — Vietnamese evaluation set (do this first)

Twenty fixed questions a real Vietnamese senior in Australia would actually ask, written **before** any prompt tuning so the prompts cannot be tuned to them.

Each entry carries:

```json
{
  "id": "vi-004",
  "query_vi": "Toi nhan duoc tin nhan la vao link de nhan tien",
  "query_vi_diacritics": "Tôi nhận được tin nhắn lạ, vào link để nhận tiền",
  "intent": "sms_phishing_scam",
  "expected_query_en": "how to identify scam text message australia",
  "expected_source_domain": "scamwatch.gov.au",
  "should_refuse": false,
  "notes": "Typed without diacritics — the common case on a phone keyboard."
}
```

Coverage should span the real problems, not toy ones:

- Scam SMS / phone calls / "you have won" messages
- myGov and Centrelink login, and the 6-digit code (two-factor authentication)
- Medicare Express Plus app
- Video calling family overseas
- Wi-Fi, data and "my phone is slow"
- Password reset
- **At least 3 out-of-scope questions that must be refused** (e.g. medical advice, visa/immigration advice, "should I buy this phone")

The refusal cases matter as much as the answerable ones — the README treats the refusal path as a real path, and my set has to prove it works in Vietnamese.

### D2 — Vietnamese input handling (feeds `s07_query.py`)

Three real problems the pipeline does not currently handle:

1. **Diacritics are optional in practice.** Seniors type `toi bi lua dao` not `tôi bị lừa đảo`. `langdetect` frequently misidentifies undiacriticised Vietnamese. Deliverable: a test set of 40 short strings (half with dấu, half without) with measured detection accuracy, plus a fallback rule — trust the language the app already knows over the detector, and only guess for typed free text.
2. **Vague phrasing → retrievable intent.** `"Điện thoại cứ đòi mã"` must rewrite to `two-factor authentication verification code`. This is the same job the README describes for Mandarin, done for Vietnamese, with the ten worst real phrasings as the test.
3. **Term expansion that keeps Australian proper nouns intact.** `myGov`, `Centrelink`, `Medicare`, `Scamwatch` must survive translation untranslated. A single mistranslation here breaks retrieval entirely.

### D3 — Vietnamese termbase and register rules (feeds `s08_prompt.py`)

**Register is not cosmetic in Vietnamese — it is the difference between respectful and insulting.** Addressing a 75-year-old as `bạn` (peer) instead of `ông` / `bà` / `cô` / `chú` is a product failure for a service aimed at seniors.

Deliverable: `prompts/vi_style.md` plus a locked glossary, e.g.

| English | Vietnamese (locked) | Do not use |
|---|---|---|
| scam | lừa đảo | gian lận |
| two-factor code | mã xác thực hai bước | mã bảo mật |
| account | tài khoản | — |
| myGov / Centrelink / Medicare | *keep in English* | any translation |

Plus plain-language rules: short sentences, numbered steps, avoid heavy Sino-Vietnamese vocabulary where a plain word exists, second person as `ông/bà` by default.

### D4 — A readability metric that works for Vietnamese

Flesch–Kincaid is meaningless in Vietnamese (monosyllabic writing system — every syllable is a word). The eval harness needs a substitute or the readability score is noise.

Deliverable: a simple documented proxy — mean words per sentence, mean syllables per word, rate of untranslated English loanwords, share of sentences over 20 words — calibrated against a handful of Vietnamese community-health leaflets as the "good" reference.

This is a small, self-contained, genuinely novel piece of work, and it is easy to write up.

### D5 — Provider bake-off for Vietnamese

Run D1's twenty questions through each candidate and score them:

- Gemini free tier (the default)
- Ollama `qwen2.5:7b` (the offline fallback — **its Vietnamese is noticeably weaker than its Chinese**, which is a real risk to the fallback path)
- One Southeast-Asian-tuned alternative, e.g. `SeaLLM` or a Vietnamese-tuned 7B

Score on groundedness, citation validity, D4 readability, refusal correctness, and register correctness. Output a table and a recommendation. If the fallback model turns out to be unusable in Vietnamese, that is a finding worth reporting, not a failure.

### D6 — Human validation (do not skip)

Twenty generated answers, rated by one or two native Vietnamese speakers on a 1–5 scale for *understandable*, *respectful*, *would follow these steps*. Twenty minutes of someone's time, and it is the only evidence in the whole project that the output works for the actual reader.

### D7 — Stretch: light fine-tune

Only after D1–D6. A LoRA adapter on a 7B base, trained on ~200 Vietnamese plain-language question/answer pairs in the house style, to see whether it beats prompting alone on the D4 readability and register scores. Framed honestly as an experiment with a measured result — a negative result is still a result.

---

## 4. Suggested sequence

| Week | Work |
|---|---|
| 1 | D1 eval set written and reviewed. D2 detection test set built. |
| 2 | D2 query rewriting working against `fixtures/f06_retrieved.json`. D3 termbase drafted. |
| 3 | D3 wired into the prompt template. D4 readability metric implemented. |
| 4 | D5 bake-off run and scored. |
| 5 | D6 human validation. Write-up. |
| 6 | D7 if time allows; otherwise polish the report. |

---

## 5. What I need from the team

- Confirmation from the group leader that the Vietnamese layer is mine end to end
- The client's approved domain list, so my expected-source answers in D1 point at pages that are actually in the knowledge base
- Whether the app passes the user's chosen language to `/ask`, or whether detection is the only signal
- One or two Vietnamese-speaking contacts for D6

---

## 6. One-line summary for the group

> I own Vietnamese: the eval set that proves the system works for Vietnamese seniors, the query rewriting and termbase that make retrieval and wording correct, a readability metric appropriate to the language, and the model comparison that says which provider we should actually ship.
