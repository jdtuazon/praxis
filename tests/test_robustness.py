"""Regression tests for two production bugs hit in live mode:

A. A Linear HTTP error (e.g. a 400 from a bad GraphQL filter) must surface as a
   structured ``PlatformError`` — which the executor handles as a failed step —
   not a raw ``httpx`` error that escapes the run endpoint as a 500.
B. The single shared SQLite connection must tolerate concurrent access from the
   server's threadpool (``/api/run`` and ``/api/memory`` land on different
   threads); without serialization sqlite raises "bad parameter or other API
   misuse" and cursors start returning ``None``.
"""

from __future__ import annotations

import threading

import pytest

from praxis.memory.store import MemoryStore
from praxis.platform.base import PlatformError
from praxis.platform.linear.client import HttpxTransport


# ── Bug A: HTTP errors become PlatformError ──────────────────────────────────
class _FakeResp:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def _transport_returning(resp, monkeypatch) -> HttpxTransport:
    t = HttpxTransport("https://example.test/graphql", "key")
    monkeypatch.setattr(t._client, "post", lambda *a, **k: resp)
    return t


def test_http_400_with_graphql_errors_becomes_platform_error(monkeypatch):
    resp = _FakeResp(
        400,
        {"errors": [{"message": "filter is not valid", "extensions": {"code": "INVALID_INPUT"}}]},
    )
    t = _transport_returning(resp, monkeypatch)
    with pytest.raises(PlatformError) as ei:
        t.execute("query { issues { nodes { id } } }", {})
    assert ei.value.status == 400
    assert ei.value.code == "INVALID_INPUT"
    assert "filter is not valid" in str(ei.value)


def test_http_error_without_json_body_becomes_platform_error(monkeypatch):
    resp = _FakeResp(401, payload=None, text="Unauthorized")
    t = _transport_returning(resp, monkeypatch)
    with pytest.raises(PlatformError) as ei:
        t.execute("query { viewer { id } }", {})
    assert ei.value.status == 401
    assert ei.value.code == "HTTP_401"


def test_rate_limit_still_raises_ratelimited(monkeypatch):
    t = _transport_returning(_FakeResp(429), monkeypatch)
    with pytest.raises(PlatformError) as ei:
        t.execute("query { viewer { id } }", {})
    assert ei.value.is_rate_limit


# ── Bug B: the shared connection is thread-safe ──────────────────────────────
def test_store_handles_concurrent_thread_access():
    """Mirror the server: writers (a run) and readers (the memory endpoint)
    hitting one connection from many threads must not corrupt it."""
    store = MemoryStore(":memory:")
    errors: list[str] = []

    def worker(wid: int) -> None:
        try:
            for i in range(150):
                store.execute(
                    "INSERT INTO instructions(text, signature, created_at) VALUES (?,?,?)",
                    (f"w{wid}-{i}", "sig", store.now()),
                )
                store.commit()
                store.counts()
                store.one("SELECT COUNT(*) AS n FROM capabilities")
                store.query("SELECT text FROM instructions LIMIT 3")
        except Exception as e:  # noqa: BLE001 — capture any error from the thread
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent store access raised: {errors[:3]}"
    # And the writes landed: 8 workers × 150 inserts.
    assert store.counts()["instructions"] == 8 * 150
