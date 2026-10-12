"""Check that a provider is actually configured and reachable.

    python check_provider.py

Run this before any eval you intend to quote. The whole point of the
project's fallback chain is that a dead provider degrades quietly to the
mock -- which is correct behaviour for a senior using the app, and the most
confusing possible failure for someone writing up results. This script is
the thing that tells you which one you have.

It never prints the key. Only its length, its first characters, and what
the API said back.
"""

from __future__ import annotations

import os
import sys

import llm  # noqa: F401  -- importing the package loads .env

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

# What Google actually issues, and what each one is for.
SHAPES = [
    ("AIzaSy", "Gemini API key (classic)", "x-goog-api-key",
     "Does not expire.", True),
    ("AQ.", "Gemini API key (newer format)", "x-goog-api-key",
     "Does not expire. Issued by AI Studio alongside the AIzaSy… format.", True),
    ("ya29.", "Google OAuth access token", "Authorization: Bearer",
     "Short-lived -- about an hour -- then every call fails until it is "
     "refreshed. Fine for one run, wrong for demo day.", True),
    ("sk-", "OpenAI-style key", "n/a",
     "WRONG PROVIDER. This project talks to Gemini and Ollama.", False),
]


def describe(key: str) -> tuple[str, str, str, bool]:
    for prefix, name, scheme, note, ok in SHAPES:
        if key.startswith(prefix):
            return name, scheme, note, ok
    # Default to the API-key header. Assuming an unknown prefix means OAuth
    # is how a working key gets a 401 -- which is exactly what happened to
    # the AQ.… format before it was added above.
    return ("unrecognised prefix", "x-goog-api-key",
            "Not a shape this script knows; it will be tried as an API key, "
            "which is the safer default.", True)


def check_ollama() -> int:
    """Is a local model actually serving? No key involved anywhere."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    want = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    print(f"  OLLAMA_HOST    {host}")
    print(f"  OLLAMA_MODEL   {want}")
    print("\n  contacting the local server…")
    try:
        import httpx
        r = httpx.get(f"{host}/api/tags", timeout=10.0)
    except Exception as exc:                       # noqa: BLE001
        print(f"  cannot reach it: {type(exc).__name__}")
        print("\n  Ollama is not running. Install it from https://ollama.com,")
        print("  then in a separate terminal:")
        print("      ollama pull qwen2.5:7b")
        print("      ollama serve")
        return 3

    if r.status_code >= 400:
        print(f"  HTTP {r.status_code}: {r.text[:200]}")
        return 4

    names = [m.get("name", "") for m in r.json().get("models", [])]
    print(f"  HTTP 200 · {len(names)} model(s) installed")
    for n in names[:8]:
        print(f"    - {n}")
    if not any(n.split(":")[0] == want.split(":")[0] for n in names):
        print(f"\n  {want} is not installed. Run:")
        print(f"      ollama pull {want}")
        return 5

    print("\nWorking, and no API key needed. Now run:")
    print("    python -m llm.eval --provider ollama")
    print("\n  Note: qwen2.5:7b's Chinese is stronger than its Vietnamese.")
    print("  If the VI lane scores badly that is a finding for the report,")
    print("  not a defect to hide.")
    return 0


def main() -> int:
    print("\nProvider check")
    print("=" * 62)

    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    print(f"  LLM_PROVIDER   {provider or '(unset)'}")

    # Ollama needs no credential at all, so it is checked on its own terms.
    if provider == "ollama" or (not os.getenv("GEMINI_API_KEY") and provider != "gemini"):
        if provider == "ollama":
            return check_ollama()

    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        print("  GEMINI_API_KEY (not set)")
        print("\nNothing to check. Two ways forward:")
        print("\n  A. Gemini — copy .env.example to .env and add:")
        print("       LLM_PROVIDER=gemini")
        print("       GEMINI_API_KEY=<key from https://aistudio.google.com/apikey>")
        print("\n  B. Ollama — no key, no account, runs on this laptop:")
        print("       install from https://ollama.com")
        print("       ollama pull qwen2.5:7b")
        print("       then set LLM_PROVIDER=ollama in .env")
        return 1

    name, scheme, note, shape_ok = describe(key)
    print(f"  GEMINI_API_KEY {key[:6]}… ({len(key)} characters)")
    print(f"  looks like     {name}")
    print(f"  sent as        {scheme}")
    print(f"  {'note' if shape_ok else 'STOP'}           {note}")

    if not shape_ok:
        print("\nGet a Gemini API key instead:")
        print("  1. Open https://aistudio.google.com/apikey")
        print("  2. Click 'Create API key'")
        print("  3. It should begin with 'AIzaSy' and be about 39 characters")
        return 2

    # Build the same headers the provider builds, so this script tests what
    # will actually run rather than an idealised version of it.
    from llm.providers.gemini import GeminiProvider
    headers = GeminiProvider(api_key=key)._headers()

    print("\n  calling the API…")
    try:
        import httpx
        r = httpx.get(ENDPOINT, headers=headers, timeout=20.0)
    except Exception as exc:                       # noqa: BLE001
        print(f"  request failed: {type(exc).__name__}: {exc}")
        return 3

    print(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        try:
            models = [m["name"].split("/")[-1] for m in r.json().get("models", [])]
        except Exception:                          # noqa: BLE001
            models = []
        flash = [m for m in models if "flash" in m][:6]
        print(f"  {len(models)} models available")
        if flash:
            print("  flash models:", ", ".join(flash))
        want = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
        listed = "(listed)" if want in models else (
            "(not in the list - check the spelling, though it may still "
            "resolve as an alias)")
        print(f"  GEMINI_MODEL   {want}  {listed}")
        print("\nWorking. Now run:")
        print("    python -m llm.eval --provider gemini")
        return 0

    if r.status_code in (400, 401, 403):
        print("  The credential was rejected. Common causes:")
        if not key.startswith("AIza"):
            print("    - an OAuth token that has already expired (they last "
                  "about an hour) — generate a fresh one and try again")
            print("    - the token's scope does not cover this API")
            print("    - the billing project is not named; try setting "
                  "GOOGLE_CLOUD_PROJECT=<your project id> in .env")
        print("    - the Generative Language API is not enabled on that project")
        print("    - the credential was revoked, or is restricted to other APIs")
    elif r.status_code == 429:
        print("  Quota exhausted. The key is valid; you are rate limited.")
    print(f"  body: {r.text[:300]}")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
