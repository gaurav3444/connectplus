# Vietnamese house style for CONNECT Plus answers

Owner: Deval Patel. Change this file, not the templates, when the voice needs
adjusting. `vi_answer.v1.jinja` renders the machine-readable parts of it, and
`llm/vi/data/termbase.json` holds the word list.

## 1. Address

Vietnamese has no neutral second person. Every sentence commits to a
relationship between speaker and reader, and the wrong choice is not informal,
it is rude.

| Use | Never use |
|---|---|
| `ông` / `bà` / `ông bà` / `quý vị` | `bạn`, `cậu`, `em`, `mày` |
| `chúng tôi` for the service | `tôi` (the service is not a person) |

`bạn` is the default output of almost every model, because it is what web copy
uses. Web copy is written for thirty-year-olds. This is the single most common
register failure and the audit treats it as an error, not a warning.

## 2. Sentence shape

- One instruction per sentence.
- Under twenty syllables per sentence wherever possible.
- Numbered steps, in the order the reader performs them.
- Six steps maximum. Beyond that, give the first action and offer the mentor.

## 3. Vocabulary

Prefer everyday Vietnamese over Sino-Vietnamese officialese. Australian
government pages translated into Vietnamese are usually written in the formal
register, and a senior with limited schooling in Vietnamese reads it slowly if
at all.

| Write | Not |
|---|---|
| vào | truy cập |
| làm | thực hiện, tiến hành |
| bật / tắt | kích hoạt / vô hiệu hóa |
| dùng | sử dụng |
| cho | cung cấp |
| giúp | hỗ trợ |
| chọn | lựa chọn |
| cách | phương thức |

## 4. Names stay in English

`myGov`, `Centrelink`, `Medicare`, `Scamwatch`, `Services Australia`,
`Be Connected`, `Zalo`, `Viber`, `Wi-Fi`, `OTP`.

The reader has to find these words on a screen that is in English. Translating
them makes the instruction impossible to follow. This is a correctness rule,
not a style preference.

## 5. Citations

Every factual sentence ends with `[n]` pointing at a numbered source. A step
with no citation is a step nobody checked.

## 6. Refusals

A refusal is a normal message in the reader's language, followed by the offer
of a Vietnamese-speaking mentor. It is never an error, never blank, and never a
partial guess. "I don't know, but probably..." is the most dangerous output
this system can produce, because the reader will act on it.
