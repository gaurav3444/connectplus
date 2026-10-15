import pytest

import rag.s01_ingest as ingest_module


@pytest.fixture(autouse=True)
def no_real_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage 01's politeness delay (time.sleep between fetches) is correct
    in production and pointless in tests, which use a mock transport with
    no real server to be polite to. Patched to a no-op so the suite stays
    fast; production behaviour is untouched.
    """
    monkeypatch.setattr(ingest_module.time, "sleep", lambda *_args, **_kwargs: None)
