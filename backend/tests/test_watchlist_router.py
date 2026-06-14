"""Integration tests for the watchlist API (issue #321 / PRD #213 R2–R4).

Full backend stack via the ``client`` fixture (FastAPI TestClient + in-memory
SQLite from ``conftest.py``). Exercises each endpoint plus the idempotency,
normalization, and empty-ticker-validation behavior. The persistence-across-
restart AC lives in ``test_watchlist_persistence.py`` (it needs an on-disk DB
across two engine sessions, which the in-memory fixture cannot model).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, WatchlistTicker
from app.services.watchlist import add_ticker, list_watchlist


@pytest.fixture()
def db_session():
    """In-memory SQLite session for direct service-level watchlist tests.

    Mirrors the conftest ``client`` fixture's engine setup but yields a raw
    session so the atomic-add tests (#326) can drive ``add_ticker`` directly
    and exercise the ``IntegrityError`` path the concurrency race triggers.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


# --- GET /api/watchlist ---


@pytest.mark.integration
def test_get_empty_watchlist_returns_empty_list(client):
    """I1 — a fresh watchlist returns 200 with an empty ``tickers`` list."""
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json() == {"tickers": []}


# --- POST /api/watchlist (add) ---


@pytest.mark.integration
def test_post_adds_ticker_and_it_appears_in_list(client):
    """I2 — an added ticker appears in the POST response and the GET list."""
    post = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert post.status_code == 200
    assert post.json() == {"tickers": ["AAPL"]}

    listed = client.get("/api/watchlist")
    assert listed.json() == {"tickers": ["AAPL"]}


@pytest.mark.integration
def test_post_normalizes_to_uppercase(client):
    """I3 — a lowercase ticker is stored + returned uppercase (aapl → AAPL)."""
    resp = client.post("/api/watchlist", json={"ticker": "aapl"})
    assert resp.status_code == 200
    assert resp.json() == {"tickers": ["AAPL"]}


@pytest.mark.integration
def test_post_duplicate_is_noop(client):
    """I4 — adding the same ticker twice yields one entry, both calls 200."""
    first = client.post("/api/watchlist", json={"ticker": "MSFT"})
    second = client.post("/api/watchlist", json={"ticker": "MSFT"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"tickers": ["MSFT"]}


@pytest.mark.integration
def test_post_duplicate_different_case_is_noop(client):
    """I5 — ``AAPL`` then ``aapl`` collapse onto one normalized entry."""
    client.post("/api/watchlist", json={"ticker": "AAPL"})
    resp = client.post("/api/watchlist", json={"ticker": "aapl"})
    assert resp.status_code == 200
    assert resp.json() == {"tickers": ["AAPL"]}


# --- DELETE /api/watchlist/{ticker} (remove) ---


@pytest.mark.integration
def test_delete_removes_ticker(client):
    """I6 — a removed ticker no longer appears in the list."""
    client.post("/api/watchlist", json={"ticker": "AAPL"})
    deleted = client.delete("/api/watchlist/AAPL")
    assert deleted.status_code == 200
    assert deleted.json() == {"tickers": []}

    listed = client.get("/api/watchlist")
    assert listed.json() == {"tickers": []}


@pytest.mark.integration
def test_delete_missing_ticker_is_noop(client):
    """I7 — removing a ticker that isn't present is a no-op (200, no error)."""
    resp = client.delete("/api/watchlist/TSLA")
    assert resp.status_code == 200
    assert resp.json() == {"tickers": []}


@pytest.mark.integration
def test_delete_normalizes_path_param(client):
    """I8 — DELETE .../aapl removes the AAPL row (path param normalized)."""
    client.post("/api/watchlist", json={"ticker": "AAPL"})
    deleted = client.delete("/api/watchlist/aapl")
    assert deleted.status_code == 200
    assert deleted.json() == {"tickers": []}


# --- validation ---


@pytest.mark.integration
@pytest.mark.parametrize("blank", ["", "   "])
def test_post_empty_ticker_returns_422(client, blank):
    """I9 — a blank ticker is rejected with 422 (no ``str(e)`` leakage)."""
    resp = client.post("/api/watchlist", json={"ticker": blank})
    assert resp.status_code == 422
    # Sanitized FastAPI validation body — no raw exception text.
    body = resp.json()
    assert "detail" in body


# --- list ordering ---


@pytest.mark.integration
def test_get_list_is_returned_in_stable_order(db_session):
    """I10 — the list endpoint returns tickers oldest-added first (#326 nit).

    Rewritten off the router path to seed **distinct** ``added_at`` values so
    the assertion genuinely proves insertion-order sort. The original
    three-rapid-POST version could share an identical ``added_at`` and pass by
    the alphabetical (``AAPL < MSFT < NVDA``) tiebreaker accident rather than
    by true oldest-first ordering. Here the rows are inserted in reverse
    alphabetical order with increasing timestamps, so an alpha-only sort would
    fail and only an ``added_at``-primary sort produces the expected list.
    """
    db_session.add_all(
        [
            WatchlistTicker(ticker="NVDA", added_at="2026-01-01T00:00:00+00:00"),
            WatchlistTicker(ticker="MSFT", added_at="2026-01-02T00:00:00+00:00"),
            WatchlistTicker(ticker="AAPL", added_at="2026-01-03T00:00:00+00:00"),
        ]
    )
    db_session.commit()
    assert list_watchlist(db_session) == ["NVDA", "MSFT", "AAPL"]


# --- add_ticker atomicity (#326 — present-check-then-insert race) ---


@pytest.mark.integration
def test_add_ticker_duplicate_integrityerror_is_noop(db_session):
    """A pre-existing row + a forced insert path is an idempotent no-op (#326).

    Simulates the concurrency race: two callers both pass the present-check
    and race to ``INSERT`` the same primary key. We pre-insert the row, then
    bypass the fast-path present-check so ``add_ticker`` attempts the insert
    and trips the ``ticker`` PK ``IntegrityError`` — which must be caught,
    rolled back, and collapsed to the documented no-op (returns the unchanged
    list, never raises). This exercises the exact code path the race triggers;
    genuinely concurrent two-thread racing is not deterministically assertable
    in-process (per the Wave 3 pilot lesson on not faking concurrency).
    """
    db_session.add(
        WatchlistTicker(ticker="AAPL", added_at="2026-01-01T00:00:00+00:00")
    )
    db_session.commit()

    # Force the insert path even though the row exists: patch the fast-path
    # present-check to report "absent" so the service reaches the INSERT.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db_session, "get", lambda *a, **k: None)
        result = add_ticker(db_session, "AAPL")

    # No raise; the unchanged single-entry list is returned.
    assert result == ["AAPL"]
    assert list_watchlist(db_session) == ["AAPL"]


@pytest.mark.integration
def test_add_ticker_atomic_no_check_then_insert_gap(db_session):
    """The success path commits exactly one row; re-adding does not raise (#326).

    Proves the happy path is unchanged (one row committed) and that a second
    ``add_ticker`` of the same ticker is an idempotent no-op even when the
    insert is attempted — the atomic ``try/except IntegrityError`` guard, not
    the present-check, is what makes the duplicate safe.
    """
    first = add_ticker(db_session, "msft")
    assert first == ["MSFT"]
    assert db_session.query(WatchlistTicker).count() == 1

    # Force the insert path on the duplicate add — must not raise.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db_session, "get", lambda *a, **k: None)
        second = add_ticker(db_session, "msft")

    assert second == ["MSFT"]
    assert db_session.query(WatchlistTicker).count() == 1
