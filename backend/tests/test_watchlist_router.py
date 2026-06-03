"""Integration tests for the watchlist API (issue #321 / PRD #213 R2–R4).

Full backend stack via the ``client`` fixture (FastAPI TestClient + in-memory
SQLite from ``conftest.py``). Exercises each endpoint plus the idempotency,
normalization, and empty-ticker-validation behavior. The persistence-across-
restart AC lives in ``test_watchlist_persistence.py`` (it needs an on-disk DB
across two engine sessions, which the in-memory fixture cannot model).
"""

from __future__ import annotations

import pytest


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
def test_get_list_is_returned_in_stable_order(client):
    """I10 — the list endpoint returns tickers oldest-added first."""
    for symbol in ("AAPL", "MSFT", "NVDA"):
        client.post("/api/watchlist", json={"ticker": symbol})
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json() == {"tickers": ["AAPL", "MSFT", "NVDA"]}
