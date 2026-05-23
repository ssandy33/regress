"""Tests for Section A — Business snapshot service (issue #280, W-A).

Covers :func:`app.services.research_business.build_business_payload` plus
the two-tier cache and the sanitized-502 error path. The yfinance call
is always patched via the ``fetcher`` injection hook on the service
function — no real Yahoo Finance traffic in tests.

These tests are service-level (not HTTP). The HTTP wiring lives in
``backend/app/routers/research.py`` (owned by Worker W); when that router
lands, it will map :class:`ResearchSourceUnavailable` to a 502 with the
same sanitized detail the service exposes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.database import AppSetting
from app.services import research_business, research_cache


@pytest.fixture(autouse=True)
def _clear_research_cache():
    """Drop the in-memory research cache between tests."""
    research_cache.clear()
    yield
    research_cache.clear()


def _seed_position(client, *, ticker: str = "SOFI", pos_id: str = "p-1") -> str:
    """Insert a position so the future router has something to look up."""
    from app.main import app
    from app.models.database import Position, get_db

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        pos = Position(
            id=pos_id,
            ticker=ticker,
            shares=100,
            broker_cost_basis=2856.0,
            status="open",
            strategy="csp",
            opened_at="2024-01-01",
        )
        db.add(pos)
        db.commit()
    finally:
        db.close()
    return pos_id


def _db_session(client):
    """Pull a session bound to the in-memory test DB."""
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    return next(override())


def _fake_info(**overrides: Any) -> dict[str, Any]:
    """Build a yfinance-shaped business info dict for fixtures."""
    base = {
        "name": "SoFi Technologies, Inc.",
        "long_business_summary": "SoFi is a personal finance company.",
        "sector": "Financial Services",
        "industry": "Credit Services",
        "market_cap": 18230000000,
        "employees": 4900,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_build_business_payload_success_returns_payload(client):
    """yfinance returns full info → payload matches PRD contract verbatim."""
    _seed_position(client)
    db = _db_session(client)
    fetcher = MagicMock(return_value=_fake_info())

    payload = research_business.build_business_payload(
        db, "SOFI", fetcher=fetcher
    )

    assert payload["ticker"] == "SOFI"
    assert payload["name"] == "SoFi Technologies, Inc."
    assert payload["summary"].startswith("SoFi is")
    assert payload["sector"] == "Financial Services"
    assert payload["industry"] == "Credit Services"
    assert payload["market_cap"] == 18230000000
    assert payload["employees"] == 4900
    assert payload["source"] == "yfinance"
    # ISO-8601 with trailing Z per PRD example
    assert payload["fetched_at"].endswith("Z")
    fetcher.assert_called_once_with("SOFI")


def test_build_business_payload_normalizes_ticker_to_upper(client):
    """Lowercase ticker is uppercased before the fetch and in the payload."""
    _seed_position(client, ticker="sofi")
    db = _db_session(client)
    fetcher = MagicMock(return_value=_fake_info())

    payload = research_business.build_business_payload(
        db, "sofi", fetcher=fetcher
    )

    assert payload["ticker"] == "SOFI"
    fetcher.assert_called_once_with("SOFI")


def test_build_business_payload_surfaces_partial_fields_as_none(client):
    """yfinance omitted fields → JSON null, not fabricated values."""
    _seed_position(client)
    db = _db_session(client)
    fetcher = MagicMock(
        return_value=_fake_info(
            employees=None,
            market_cap=None,
            industry=None,
        )
    )

    payload = research_business.build_business_payload(
        db, "SOFI", fetcher=fetcher
    )

    assert payload["employees"] is None
    assert payload["market_cap"] is None
    assert payload["industry"] is None
    # Other fields untouched
    assert payload["sector"] == "Financial Services"


# ---------------------------------------------------------------------------
# Upstream failure → 502 (sanitized)
# ---------------------------------------------------------------------------


def test_build_business_payload_raises_when_yfinance_returns_none(client):
    """yfinance hard fail → ResearchSourceUnavailable with sanitized detail."""
    _seed_position(client)
    db = _db_session(client)
    fetcher = MagicMock(return_value=None)

    with pytest.raises(research_business.ResearchSourceUnavailable) as exc:
        research_business.build_business_payload(db, "SOFI", fetcher=fetcher)

    # CLAUDE.md compliance: the detail string is the generic
    # "Source unavailable" message, never an inner exception's str().
    assert exc.value.detail == "Source unavailable"
    assert str(exc.value) == "Source unavailable"


# ---------------------------------------------------------------------------
# Cache hit — in-memory tier
# ---------------------------------------------------------------------------


def test_in_memory_cache_hit_skips_yfinance_on_second_call(client):
    """Second call inside TTL serves from research_cache — no fetcher call."""
    _seed_position(client)
    db = _db_session(client)
    fetcher = MagicMock(return_value=_fake_info())

    first = research_business.build_business_payload(
        db, "SOFI", fetcher=fetcher
    )
    second = research_business.build_business_payload(
        db, "SOFI", fetcher=fetcher
    )

    assert first == second
    assert fetcher.call_count == 1


# ---------------------------------------------------------------------------
# Cache hit — durable app_settings tier
# ---------------------------------------------------------------------------


def test_app_setting_cache_hit_skips_yfinance_after_in_memory_eviction(
    client,
):
    """Pre-seed app_settings → call serves the row without hitting yfinance."""
    _seed_position(client)
    db = _db_session(client)

    fixture_payload = {
        "ticker": "SOFI",
        "name": "SoFi Technologies, Inc.",
        "summary": "Pre-seeded.",
        "sector": "Financial Services",
        "industry": "Credit Services",
        "market_cap": 18230000000,
        "employees": 4900,
        "source": "yfinance",
        "fetched_at": "2026-05-22T17:30:00Z",
    }
    import json

    fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(
        AppSetting(
            key="yf_business:SOFI",
            value=f"{fetched_at.isoformat()}|{json.dumps(fixture_payload)}",
        )
    )
    db.commit()

    # In-memory tier is empty (autouse fixture) — only the app_settings
    # row should resolve this call.
    fetcher = MagicMock(return_value=_fake_info(name="WRONG"))
    payload = research_business.build_business_payload(
        db, "SOFI", fetcher=fetcher
    )

    fetcher.assert_not_called()
    assert payload["name"] == "SoFi Technologies, Inc."
    assert payload["summary"] == "Pre-seeded."


def test_stale_app_setting_falls_through_to_yfinance(client):
    """app_settings row older than 24h → yfinance is called again."""
    _seed_position(client)
    db = _db_session(client)

    stale_payload = {
        "ticker": "SOFI",
        "name": "STALE",
        "summary": "Stale.",
        "sector": "Financial Services",
        "industry": "Credit Services",
        "market_cap": 1,
        "employees": 1,
        "source": "yfinance",
        "fetched_at": "2025-01-01T00:00:00Z",
    }
    import json

    fetched_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db.add(
        AppSetting(
            key="yf_business:SOFI",
            value=f"{fetched_at.isoformat()}|{json.dumps(stale_payload)}",
        )
    )
    db.commit()

    fetcher = MagicMock(return_value=_fake_info(name="FRESH"))
    payload = research_business.build_business_payload(
        db, "SOFI", fetcher=fetcher
    )

    fetcher.assert_called_once_with("SOFI")
    # Fresh fetcher value is surfaced, not the stale app_settings row
    assert payload["name"] == "FRESH"
    assert payload["name"] != "STALE"
