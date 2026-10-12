"""Optional offline translation fallback for the Chinese lanes.

**The problem this closes.** :class:`llm.providers.mock.MockProvider` is
deliberately not a language model: its own docstring records that it copies
source text into the answer *in English*, and that every mock-served
Chinese or Vietnamese question therefore grades ``hard`` on readability
because the language-integrity cap is correctly catching untranslated
English. That is fine for exercising the pipeline with no API key and no
network, which is the whole point of the mock -- but it means anyone running
fully offline currently gets an English answer dressed in Chinese
scaffolding, not a Chinese answer.

**Why this is not a** :class:`~llm.providers.base.Provider`. Gemini and
Ollama are instruction-followers: they read a full ``TASK: ANSWER`` prompt
-- role, register rules, the glossary, the fenced sources, the citation
format -- and reason about all of it at once. NLLB-200 is a pure
translation model with no instruction-following ability at all; handing it
that whole rendered prompt would not "answer" it, it would mistranslate the
instructions themselves. So this module does one narrow, honest thing
instead: translate already-generated English text into Traditional
Mandarin. It is a post-processing step, called after generation, not a
provider swapped in before it.

**Why it is opt-in.** ``torch`` and ``transformers`` are a multi-gigabyte,
GPU-shaped dependency that nothing else in this repo needs. Importing them
is deferred into the function body, and the function itself is a no-op
unless ``CONNECTPLUS_NLLB_MODEL_DIR`` is set, so a teammate who has not
installed the fine-tuning stack sees no change in behaviour at all -- the
existing English-scaffolding fallback keeps working exactly as before.

**Scope.** Only fires for the ``zh_hant`` lane, on the mock provider, and
translates line by line rather than the whole answer at once -- only the
lines the mock actually leaves untranslated (see the docstring on
:func:`maybe_translate_fallback`) are touched; the mock's own hand-written
Chinese opening and mentor lines are left exactly as generated. Extending
this to the ``zh`` (Simplified) or ``vi`` (Vietnamese) lane, or to a real
provider's occasional English slip, is a one-line change once each lane's
own team is satisfied with translation quality on their language; it is
left off by default here because this model was only trained and evaluated
on the zh_hant direction.
"""

from __future__ import annotations

import os
from functools import lru_cache

from ..lang.detect import has_cjk

__all__ = ["maybe_translate_fallback", "translate_en_to_zh_hant"]

_SRC_LANG = "eng_Latn"
_TGT_LANG = "zho_Hant"
_MAX_LEN = 128


def _model_dir() -> str | None:
    return os.getenv("CONNECTPLUS_NLLB_MODEL_DIR") or None


@lru_cache(maxsize=1)
def _load():
    """Load the fine-tuned model and tokenizer once, lazily.

    Deferred import: a machine with no GPU and no ``torch`` installed can
    import this whole module, call :func:`maybe_translate_fallback`, and get
    the untouched input back, with nothing above this function ever knowing
    the dependency was missing.
    """
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    model_dir = _model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir)
    return tokenizer, model


def translate_en_to_zh_hant(text: str) -> str:
    """Translate English text to Traditional Mandarin with the fine-tuned model.

    Args:
        text: English text to translate.

    Returns:
        The Traditional Mandarin translation. Raises whatever the underlying
        model call raises on failure -- callers that must not crash the
        pipeline should go through :func:`maybe_translate_fallback` instead,
        which catches and degrades rather than propagating.
    """
    tokenizer, model = _load()
    tokenizer.src_lang = _SRC_LANG
    encoded = tokenizer(text, return_tensors="pt", truncation=True,
                        max_length=_MAX_LEN)
    forced_bos_token_id = tokenizer.convert_tokens_to_ids(_TGT_LANG)
    generated = model.generate(**encoded, forced_bos_token_id=forced_bos_token_id,
                               max_length=_MAX_LEN, num_beams=5)
    return tokenizer.batch_decode(generated, skip_special_tokens=True)[0]


def maybe_translate_fallback(text: str, *, lang: str, provider_name: str) -> str:
    """Translate the untranslated parts of ``text``, if any, and if worth it.

    This is the function :mod:`llm.pipeline` actually calls. It is safe to
    call unconditionally on every answer: it returns ``text`` unchanged for
    every case this module is not meant to touch, and never raises -- a
    translation failure degrades to the original (English-inclusive) text
    rather than breaking the answer.

    Works line by line rather than on the whole answer at once, because
    :class:`~llm.providers.mock.MockProvider` already writes its opening and
    mentor lines as hand-written, correctly-registered Traditional Chinese
    (see its own ``_SCAFFOLD``) -- only the numbered lines it assembles from
    English source chunks are actually untranslated. Running the whole
    answer through the model regardless would mean regenerating scaffolding
    that is already correct and hand-checked, which is the one thing this
    codebase is consistently careful not to do (see ``lanes.REFUSALS``'s own
    docstring on the same point).

    Args:
        text: The generated answer.
        lang: The lane the answer was generated for.
        provider_name: Which provider actually produced ``text``. Real
            providers (Gemini, Ollama) are expected to already answer in the
            requested language; this fallback is for the mock only.

    Returns:
        ``text`` with any pure-English lines translated, everything else
        (including already-Chinese lines) left exactly as generated.
    """
    if lang != "zh_hant" or provider_name != "mock" or not text:
        return text
    if not _model_dir():
        return text

    out_lines = []
    changed = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or has_cjk(stripped):
            out_lines.append(line)
            continue
        try:
            out_lines.append(translate_en_to_zh_hant(line))
            changed = True
        except Exception:
            # Degrade this one line to its original English rather than
            # dropping it or failing the whole answer.
            out_lines.append(line)
    return "\n".join(out_lines) if changed else text
