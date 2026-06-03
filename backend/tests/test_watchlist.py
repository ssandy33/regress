"""Unit tests for the watchlist normalization + schema boundary (issue #321).

Pure-function tests — NO DB session, NO TestClient (PRD #261 R3 unit tier).
Covers :func:`app.services.watchlist.normalize_ticker` and the
:class:`WatchlistAddRequest` / :class:`WatchlistResponse` Pydantic boundaries.
The DB-backed add/remove/list/persistence behavior is exercised in the
integration suites (``test_watchlist_router.py`` /
``test_watchlist_persistence.py``).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import WatchlistAddRequest, WatchlistResponse
from app.services.watchlist import normalize_ticker


# --- normalize_ticker (PRD #213 R2 — uppercase normalization) ---


@pytest.mark.unit
def test_normalize_lowercases_to_uppercase():
    """U1 — ``aapl`` normalizes to ``AAPL`` (the headline AC)."""
    assert normalize_ticker("aapl") == "AAPL"


@pytest.mark.unit
def test_normalize_strips_surrounding_whitespace():
    """U2 — leading/trailing whitespace is stripped before uppercasing."""
    assert normalize_ticker("  msft  ") == "MSFT"


@pytest.mark.unit
def test_normalize_already_uppercase_is_idempotent():
    """U3 — an already-canonical ticker is returned unchanged."""
    assert normalize_ticker("NVDA") == "NVDA"


@pytest.mark.unit
def test_normalize_mixed_case():
    """U4 — mixed-case input collapses to all-uppercase."""
    assert normalize_ticker("AaPl") == "AAPL"


@pytest.mark.unit
def test_normalize_internal_chars_preserved():
    """U5 — internal punctuation (class-share dot) survives normalization."""
    assert normalize_ticker("brk.b") == "BRK.B"


# --- WatchlistAddRequest (boundary validation + normalization) ---


@pytest.mark.unit
@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_add_request_schema_rejects_empty_ticker(blank):
    """U6 — a blank/whitespace-only ticker is rejected at the schema boundary."""
    with pytest.raises(ValidationError):
        WatchlistAddRequest(ticker=blank)


@pytest.mark.unit
def test_add_request_schema_normalizes_ticker():
    """U7 — the request model strips + uppercases on construction."""
    assert WatchlistAddRequest(ticker="  aapl ").ticker == "AAPL"


# --- WatchlistResponse (empty-list behavior) ---


@pytest.mark.unit
def test_response_schema_defaults_to_empty_list():
    """U8 — an empty watchlist is the default, valid response (not an error)."""
    assert WatchlistResponse().tickers == []
