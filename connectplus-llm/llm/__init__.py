"""CONNECT Plus language and answer service.

Takes a senior's question in their own language, works out what they need,
retrieves trusted source material, writes a plain-language answer in that
same language, has it verified, and streams whatever survives.

Three language lanes: Chinese, Vietnamese, English. See llm/lanes.py.
"""

from pathlib import Path

__all__ = ["pipeline", "lanes", "schemas"]


def _load_env() -> None:
    """Read ``.env`` into the environment, once, on import.

    Without this the providers call ``os.getenv("GEMINI_API_KEY")``, find
    nothing, and quietly fall back to the mock -- which looks exactly like
    the pipeline working and is the most confusing way this project can
    fail. A real environment variable always wins over the file, so the
    shell and CI keep control.

    ``python-dotenv`` is optional: the repo must still run with nothing
    installed beyond the core requirements.
    """
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        # Minimal fallback, so a missing dependency never silently means
        # "no key". KEY=value with optional quotes is all a .env file is.
        import os
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return
    load_dotenv(env, override=False)


_load_env()
