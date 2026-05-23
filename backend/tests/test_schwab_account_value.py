"""Unit tests for schwab_account_value (issue #234 — W-A).

Test pattern mirrors backend/tests/test_alpha_vantage_client.py:
* Patch the durable cache helpers so we don't touch a real SQLite row
  for the cache-only tests; use the conftest in-memory client for
  persistence tests.
* Patch ``SchwabClient.get_accounts`` for every network path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import AppSetting, Base
from app.services import schwab_account_value as sav
from app.services.schwab_account_value import (
    AccountValueResult,
    clear_cache,
    get_account_value,
    get_cached_account_value,
    _CACHE_TTL,
    _DB_KEY_PREFIX,
    _cache_key,
)
from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
from app.services.schwab_client import SchwabClientError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """In-memory SQLite session for tests that exercise the durable tier."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clear_module_cache():
    """Every test starts with an empty hot cache."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account(account_number: str, net_liq: float, account_type: str = "CASH",
             *, container: str = "currentBalances", value_key: str = "liquidationValue") -> dict:
    """Build a single raw Schwab account dict with the given liquidationValue."""
    return {
        "hashValue": f"hash-{account_number}",
        "securitiesAccount": {
            "accountNumber": account_number,
            "type": account_type,
            container: {value_key: net_liq},
        },
    }


def _patch_schwab(accounts):
    """Patch ``SchwabClient.get_accounts`` to return ``accounts``.

    Pass a list for a fixed return value or an exception class/instance for
    a raising mock.
    """
    if isinstance(accounts, Exception) or (
        isinstance(accounts, type) and issubclass(accounts, BaseException)
    ):
        return patch(
            "app.services.schwab_account_value.SchwabClient.get_accounts",
            side_effect=accounts,
        )
    return patch(
        "app.services.schwab_account_value.SchwabClient.get_accounts",
        return_value=accounts,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCacheHit:
    @pytest.mark.unit
    def test_cache_hit_returns_fresh_value(self, db_session):
        """1. test_cache_hit_returns_fresh_value — within TTL, returns cached."""
        # Pre-populate the hot cache with a fresh ok result.
        now = datetime.now(timezone.utc)
        cached = AccountValueResult(
            status="ok",
            total_capital=12345.0,
            account_id_masked="…4471",
            account_type="CASH",
            accounts=[
                {"account_id_masked": "…4471", "account_type": "CASH", "net_liquidation": 12345.0}
            ],
            cached_at=now,
        )
        sav._cache[_cache_key(None)] = cached

        with _patch_schwab([_account("99999999", 0.0)]) as mock_get:
            result = get_account_value(db_session)

        assert result.status == "ok"
        assert result.total_capital == 12345.0
        assert result.account_id_masked == "…4471"
        mock_get.assert_not_called()


class TestCacheMiss:
    @pytest.mark.unit
    def test_cache_miss_calls_network(self, db_session):
        """2. test_cache_miss_calls_network — stale, calls get_accounts()."""
        with _patch_schwab([_account("12344471", 25000.0, "CASH")]) as mock_get:
            result = get_account_value(db_session)

        assert mock_get.call_count == 1
        assert result.status == "ok"
        assert result.total_capital == 25000.0
        assert result.account_id_masked == "…4471"
        assert result.account_type == "CASH"
        assert result.accounts == [
            {"account_id_masked": "…4471", "account_type": "CASH", "net_liquidation": 25000.0}
        ]
        assert result.cached_at is not None


class TestForceRefresh:
    @pytest.mark.unit
    def test_force_refresh_bypasses_cache(self, db_session):
        """3. force_refresh=True forces a network call even when the cache is fresh."""
        sav._cache[_cache_key(None)] = AccountValueResult(
            status="ok",
            total_capital=10.0,
            account_id_masked="…1111",
            cached_at=datetime.now(timezone.utc),
        )
        with _patch_schwab([_account("00004471", 99999.0)]) as mock_get:
            result = get_account_value(db_session, force_refresh=True)

        mock_get.assert_called_once()
        assert result.total_capital == 99999.0
        assert result.account_id_masked == "…4471"

    @pytest.mark.unit
    def test_force_refresh_falls_through_to_fresh_cache_on_failure(
        self, db_session, caplog
    ):
        """4. S2 contract — network fails, hot cache fresh -> returns cached ok + WARNING."""
        # Pre-populate hot cache with a fresh ok entry.
        fresh = AccountValueResult(
            status="ok",
            total_capital=42000.0,
            account_id_masked="…4471",
            account_type="MARGIN",
            accounts=[
                {"account_id_masked": "…4471", "account_type": "MARGIN", "net_liquidation": 42000.0}
            ],
            cached_at=datetime.now(timezone.utc),
        )
        sav._cache[_cache_key(None)] = fresh

        with caplog.at_level(logging.WARNING, logger="app.services.schwab_account_value"):
            with _patch_schwab(SchwabClientError("transient transport")):
                result = get_account_value(db_session, force_refresh=True)

        assert result.status == "ok"
        assert result.total_capital == 42000.0
        assert result.account_id_masked == "…4471"
        # WARNING log present
        warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("refresh failed" in m.lower() for m in warning_messages), \
            f"Expected refresh-failed warning, got: {warning_messages}"


class TestAuthStatusMapping:
    @pytest.mark.unit
    def test_disconnected_status(self, db_session):
        """5. TOKEN_MISSING / NOT_CONFIGURED -> 'disconnected'."""
        for code in (SchwabAuthCode.TOKEN_MISSING, SchwabAuthCode.NOT_CONFIGURED):
            clear_cache()
            with _patch_schwab(SchwabAuthError("schwab not configured", code=code)):
                result = get_account_value(db_session)
            assert result.status == "disconnected", f"code {code} should map to disconnected"
            assert result.total_capital is None
            # Generic sanitised error_detail; never raw exception text.
            assert result.error_detail is not None
            assert "not configured" not in (result.error_detail or "").lower() or \
                result.error_detail == "Schwab is not connected"

    @pytest.mark.unit
    def test_expired_status(self, db_session):
        """6. TOKEN_EXPIRED / REFRESH_FAILED_401 -> 'expired'."""
        for code in (
            SchwabAuthCode.TOKEN_EXPIRED,
            SchwabAuthCode.REFRESH_FAILED,
            SchwabAuthCode.REFRESH_FAILED_401,
            SchwabAuthCode.API_401,
        ):
            clear_cache()
            with _patch_schwab(SchwabAuthError("refresh failed", code=code)):
                result = get_account_value(db_session)
            assert result.status == "expired", f"code {code} should map to expired"
            assert result.total_capital is None


class TestErrorStatus:
    @pytest.mark.unit
    def test_error_status_on_transport_failure(self, db_session):
        """7. transport / client error -> 'error'."""
        with _patch_schwab(SchwabClientError("Unable to reach Schwab API")):
            result = get_account_value(db_session)
        assert result.status == "error"
        assert result.total_capital is None
        # Per CLAUDE.md, error_detail is generic — never raw exception text.
        assert result.error_detail == "Schwab API error"

    @pytest.mark.unit
    def test_error_status_on_malformed_json(self, db_session):
        """8. non-list payload from get_accounts() -> 'error'."""
        with _patch_schwab({"unexpected": "shape"}):
            result = get_account_value(db_session)
        assert result.status == "error"
        assert "malformed" in (result.error_detail or "").lower()

    @pytest.mark.unit
    def test_error_status_on_zero_liquidation_value(self, db_session):
        """9. liquidationValue == 0 -> 'error' (account-zero failure cause)."""
        with _patch_schwab([_account("00000000", 0.0)]):
            result = get_account_value(db_session)
        assert result.status == "error"
        assert "zero" in (result.error_detail or "").lower()

    @pytest.mark.unit
    def test_error_status_on_missing_liquidation_value_field(self, db_session):
        """10. all candidate keys absent -> 'error', no exception."""
        # Build a securitiesAccount with neither liquidationValue nor any
        # alternative key present.
        raw = [
            {
                "hashValue": "h",
                "securitiesAccount": {
                    "accountNumber": "11114471",
                    "type": "CASH",
                    "currentBalances": {"cashAvailableForTrading": 0.0},
                },
            }
        ]
        with _patch_schwab(raw):
            result = get_account_value(db_session)
        assert result.status == "error"
        assert "liquidationvalue" in (result.error_detail or "").lower()


class TestMultiAccountSelection:
    @pytest.mark.unit
    def test_first_account_default_selection(self, db_session):
        """11. sizing_cap_account=None -> picks the first account in the response."""
        accounts = [
            _account("11114471", 30000.0, "CASH"),
            _account("22228888", 70000.0, "MARGIN"),
        ]
        with _patch_schwab(accounts):
            result = get_account_value(db_session)

        assert result.status == "ok"
        assert result.total_capital == 30000.0  # first account
        assert result.account_id_masked == "…4471"
        assert result.account_type == "CASH"
        # accounts list still contains both sanitised entries
        assert len(result.accounts or []) == 2

    @pytest.mark.unit
    def test_sum_across_all_accounts(self, db_session):
        """12. sizing_cap_account='sum' -> sum across all sanitised accounts."""
        accounts = [
            _account("11114471", 30000.0, "CASH"),
            _account("22228888", 70000.0, "MARGIN"),
        ]
        with _patch_schwab(accounts):
            result = get_account_value(db_session, sizing_cap_account="sum")

        assert result.status == "ok"
        assert result.total_capital == 100000.0
        # The summed result has no single account_id_masked.
        assert result.account_id_masked is None
        assert len(result.accounts or []) == 2

    @pytest.mark.unit
    def test_match_by_masked_id(self, db_session):
        """13. sizing_cap_account='...4471' matches that specific account."""
        accounts = [
            _account("11114471", 30000.0, "CASH"),
            _account("22228888", 70000.0, "MARGIN"),
        ]
        with _patch_schwab(accounts):
            result = get_account_value(db_session, sizing_cap_account="…4471")

        assert result.status == "ok"
        assert result.total_capital == 30000.0
        assert result.account_id_masked == "…4471"

        # Same fixture, different masked id selects the other account.
        clear_cache()
        with _patch_schwab(accounts):
            result2 = get_account_value(db_session, sizing_cap_account="…8888")
        assert result2.status == "ok"
        assert result2.total_capital == 70000.0
        assert result2.account_id_masked == "…8888"

    @pytest.mark.unit
    def test_match_by_masked_id_not_found(self, db_session):
        """14. masked id not in response -> 'error'."""
        accounts = [_account("11114471", 30000.0, "CASH")]
        with _patch_schwab(accounts):
            result = get_account_value(db_session, sizing_cap_account="…9999")

        assert result.status == "error"
        assert result.total_capital is None
        assert "not found" in (result.error_detail or "").lower()


class TestCachedNeverCallsNetwork:
    @pytest.mark.unit
    def test_get_cached_never_calls_network(self, db_session):
        """15. get_cached_account_value never invokes Schwab even on empty cache."""
        with patch(
            "app.services.schwab_account_value.SchwabClient.get_accounts"
        ) as mock_get:
            result = get_cached_account_value(db_session)

        assert result is None  # empty hot cache + empty DB -> None (not status='error')
        mock_get.assert_not_called()

        # Even with a stale hot cache entry, no network call.
        old = datetime.now(timezone.utc) - (_CACHE_TTL + timedelta(seconds=1))
        sav._cache[_cache_key(None)] = AccountValueResult(
            status="ok",
            total_capital=1.0,
            cached_at=old,
        )
        with patch(
            "app.services.schwab_account_value.SchwabClient.get_accounts"
        ) as mock_get2:
            stale_result = get_cached_account_value(db_session)
        assert stale_result is None
        mock_get2.assert_not_called()


class TestDbPersistence:
    @pytest.mark.unit
    def test_db_persistence_across_in_memory_reset(self, db_session):
        """16. write to DB, clear in-memory, read back from DB."""
        accounts = [_account("33334471", 55000.0, "CASH")]
        with _patch_schwab(accounts):
            first = get_account_value(db_session)
        assert first.status == "ok"
        assert first.total_capital == 55000.0

        # Confirm the durable row landed.
        key = f"{_DB_KEY_PREFIX}{_cache_key(None)}"
        entry = db_session.query(AppSetting).filter(AppSetting.key == key).first()
        assert entry is not None, "DB row should be written after a successful fetch"

        # Wipe the hot cache and read again — this time without a network
        # mock; if the implementation reads from DB it must return the
        # cached value without raising.
        clear_cache()
        with patch(
            "app.services.schwab_account_value.SchwabClient.get_accounts",
            side_effect=AssertionError("must not call network when DB cache is fresh"),
        ):
            second = get_cached_account_value(db_session)

        assert second is not None
        assert second.status == "ok"
        assert second.total_capital == 55000.0
        assert second.account_id_masked == "…4471"
