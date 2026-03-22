"""Unit tests for CacheService (backend/app/services/cache.py).

Covers all four methods: get, get_stale, set, _is_fresh.
Three issue ACs reference methods that do not exist on CacheService
(delete, clear_all, get_all_keys) — those are documented as skipped tests.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, CacheEntry
from app.services.cache import CacheService


@pytest.fixture()
def db_session():
    """In-memory SQLite session for isolated cache tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def cache_service(db_session):
    """CacheService backed by the in-memory test session."""
    return CacheService(db_session)


# ---------------------------------------------------------------------------
# Round-trip: set then get
# ---------------------------------------------------------------------------


class TestSetAndGet:
    """AC: test_set_and_get_cache_entry"""

    def test_round_trip_returns_stored_data(self, cache_service):
        """set() followed by get() returns matching data, source, and frequency."""
        data = json.dumps({"prices": [1, 2, 3]})
        cache_service.set("schwab:AAPL", data, "daily", "schwab")

        result = cache_service.get("schwab:AAPL")
        assert result is not None
        assert result["data"] == data
        assert result["source_frequency"] == "daily"
        assert result["source_name"] == "schwab"
        assert result["fetched_at"] is not None


# ---------------------------------------------------------------------------
# Cache miss
# ---------------------------------------------------------------------------


class TestCacheMiss:
    """AC: test_get_returns_none_for_missing_key"""

    def test_get_returns_none_for_missing_key(self, cache_service):
        """get() returns None when no entry exists for the key."""
        assert cache_service.get("nonexistent") is None

    def test_get_stale_returns_none_for_missing_key(self, cache_service):
        """get_stale() also returns None when no entry exists."""
        assert cache_service.get_stale("nonexistent") is None


# ---------------------------------------------------------------------------
# TTL expiration
# ---------------------------------------------------------------------------


class TestExpiration:
    """AC: test_expired_entry_returns_none, test_expired_entry_get_stale_still_returns"""

    def test_expired_daily_entry_returns_none(self, cache_service, db_session):
        """get() returns None when a daily entry has exceeded the TTL."""
        cache_service.set("schwab:AAPL", '{"p":1}', "daily", "schwab")

        # Backdate fetched_at to 25 hours ago
        entry = db_session.get(CacheEntry,"schwab:AAPL")
        entry.fetched_at = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        db_session.commit()

        assert cache_service.get("schwab:AAPL") is None

    def test_expired_entry_get_stale_still_returns(self, cache_service, db_session):
        """get_stale() returns data even when the entry is expired."""
        cache_service.set("schwab:AAPL", '{"p":1}', "daily", "schwab")

        entry = db_session.get(CacheEntry,"schwab:AAPL")
        entry.fetched_at = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        db_session.commit()

        result = cache_service.get_stale("schwab:AAPL")
        assert result is not None
        assert result["data"] == '{"p":1}'

    def test_fresh_daily_entry_within_ttl(self, cache_service):
        """get() returns data for a daily entry still within the TTL window."""
        cache_service.set("schwab:AAPL", '{"p":1}', "daily", "schwab")
        assert cache_service.get("schwab:AAPL") is not None

    def test_monthly_entry_uses_monthly_ttl(self, cache_service, db_session):
        """Monthly frequency uses cache_ttl_monthly_days (7d), not the daily TTL."""
        cache_service.set("fred:GDP", '{"v":100}', "monthly", "fred")

        # 3 days old — still fresh for monthly (7d TTL)
        entry = db_session.get(CacheEntry,"fred:GDP")
        entry.fetched_at = (
            datetime.now(timezone.utc) - timedelta(days=3)
        ).isoformat()
        db_session.commit()
        assert cache_service.get("fred:GDP") is not None

        # 8 days old — expired for monthly
        entry.fetched_at = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
        db_session.commit()
        assert cache_service.get("fred:GDP") is None

    def test_quarterly_entry_uses_monthly_ttl(self, cache_service, db_session):
        """Quarterly frequency falls into the else branch, using monthly TTL."""
        cache_service.set("fred:GDPQ", '{"v":200}', "quarterly", "fred")

        entry = db_session.get(CacheEntry,"fred:GDPQ")
        entry.fetched_at = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
        db_session.commit()
        assert cache_service.get("fred:GDPQ") is None


# ---------------------------------------------------------------------------
# Upsert behavior
# ---------------------------------------------------------------------------


class TestUpsert:
    """AC: test_set_overwrites_existing_entry"""

    def test_set_overwrites_existing_entry(self, cache_service):
        """Calling set() twice with the same key updates to the latest data."""
        cache_service.set("schwab:AAPL", '{"v":1}', "daily", "schwab")
        cache_service.set("schwab:AAPL", '{"v":2}', "daily", "schwab")

        result = cache_service.get("schwab:AAPL")
        assert result is not None
        assert result["data"] == '{"v":2}'

    def test_set_overwrites_frequency_and_source(self, cache_service):
        """Upsert also updates frequency and source fields."""
        cache_service.set("schwab:AAPL", '{"v":1}', "daily", "schwab")
        cache_service.set("schwab:AAPL", '{"v":2}', "monthly", "fred")

        result = cache_service.get_stale("schwab:AAPL")
        assert result["source_frequency"] == "monthly"
        assert result["source_name"] == "fred"


# ---------------------------------------------------------------------------
# Large payload (relevant to bug #73)
# ---------------------------------------------------------------------------


class TestLargePayload:
    """AC: test_cache_with_large_payload"""

    def test_large_payload_round_trips_without_truncation(self, cache_service):
        """A ~500KB JSON payload stores and retrieves without data loss."""
        large_data = json.dumps({"values": list(range(100000))})
        assert len(large_data) > 500_000  # sanity check

        cache_service.set("large:TEST", large_data, "daily", "test")

        result = cache_service.get("large:TEST")
        assert result is not None
        assert result["data"] == large_data
        assert json.loads(result["data"]) == {"values": list(range(100000))}


# ---------------------------------------------------------------------------
# Special characters in keys
# ---------------------------------------------------------------------------


class TestSpecialCharacterKeys:
    """AC: test_cache_with_special_characters_in_key"""

    @pytest.mark.parametrize(
        "key",
        [
            "schwab:AAPL/daily",
            "fred:DGS10:2024",
            "key with spaces",
            "unicode:data-\u00e9\u00e0\u00fc",
            "slashes/and:colons/mixed",
        ],
    )
    def test_special_char_keys_round_trip(self, cache_service, key):
        """Keys containing /, :, spaces, and unicode all round-trip correctly."""
        cache_service.set(key, '{"ok":true}', "daily", "test")

        result = cache_service.get(key)
        assert result is not None
        assert result["data"] == '{"ok":true}'


# ---------------------------------------------------------------------------
# Sequential writes to same key (concurrency proxy)
# ---------------------------------------------------------------------------


class TestSequentialWrites:
    """AC: test_concurrent_writes_same_key (sequential — true concurrency not
    meaningful with single-threaded in-memory SQLite)."""

    def test_sequential_writes_no_corruption(self, cache_service):
        """Two rapid sequential set() calls leave the entry in a valid state."""
        cache_service.set("schwab:MSFT", '{"v":1}', "daily", "schwab")
        cache_service.set("schwab:MSFT", '{"v":2}', "daily", "schwab")

        result = cache_service.get("schwab:MSFT")
        assert result is not None
        assert result["data"] == '{"v":2}'


# ---------------------------------------------------------------------------
# fetched_at format
# ---------------------------------------------------------------------------


class TestFetchedAtFormat:
    def test_set_stores_valid_iso_format(self, cache_service, db_session):
        """set() writes fetched_at as a parseable ISO 8601 string."""
        cache_service.set("schwab:AAPL", '{"v":1}', "daily", "schwab")

        entry = db_session.get(CacheEntry,"schwab:AAPL")
        parsed = datetime.fromisoformat(entry.fetched_at)
        assert parsed.tzinfo is not None  # timezone-aware


# ---------------------------------------------------------------------------
# Naive datetime handling in _is_fresh
# ---------------------------------------------------------------------------


class TestNaiveDatetimeHandling:
    def test_fetched_at_without_timezone_treated_as_utc(
        self, cache_service, db_session
    ):
        """_is_fresh treats a naive fetched_at as UTC (lines 72-73 of cache.py)."""
        cache_service.set("schwab:AAPL", '{"v":1}', "daily", "schwab")

        # Replace fetched_at with a naive (no tz) ISO string set to "now"
        entry = db_session.get(CacheEntry,"schwab:AAPL")
        entry.fetched_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        db_session.commit()

        # Should still be fresh — treated as UTC, which is recent
        assert cache_service.get("schwab:AAPL") is not None


# ---------------------------------------------------------------------------
# Skipped tests — methods do not exist on CacheService
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="CacheService has no delete() method — AC not applicable (issue #82)"
)
def test_delete_cache_entry():
    """AC: test_delete_cache_entry. CacheService does not implement delete()."""


@pytest.mark.skip(
    reason="CacheService has no clear_all() method — AC not applicable (issue #82)"
)
def test_clear_all_cache():
    """AC: test_clear_all_cache. CacheService does not implement clear_all()."""


@pytest.mark.skip(
    reason="CacheService has no key-listing method — AC not applicable (issue #82)"
)
def test_get_all_cache_keys():
    """AC: test_get_all_cache_keys. CacheService does not implement get_all_keys()."""
