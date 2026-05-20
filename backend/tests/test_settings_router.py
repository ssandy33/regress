"""Tests for the issue #234 settings-router additions (Worker W-E).

This file covers the three W-E deliverables:

1. ``GET /api/settings/rules`` now carries an extra ``migration`` sibling key
   (S4 refinement) — the frontend banner reads ``migration.sizing_cap`` to
   decide whether to render the v1 → v2 sizing-cap callout. The flat
   :class:`RulesConfig` portion of the payload is unchanged and is
   covered separately in ``test_settings_rules_endpoint.py``.

2. ``POST /api/settings/rules/migration/sizing-cap/dismiss`` stamps
   ``dismissed_at`` on the one-time ``sizing_cap_migration`` marker row.
   Idempotent — a second call returns 200 and a fresh ``dismissed_at``.

3. ``GET /api/settings/account-value`` /
   ``POST /api/settings/account-value/refresh`` wrap W-A's
   :mod:`app.services.schwab_account_value`. The W-A service functions are
   mocked here so these tests don't touch a Schwab credential or the live
   cache — the wire contract is what we're asserting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.database import AppSetting, get_db
from app.services.rules_config import (
    DEFAULT_RULES_CONFIG,
    RULES_CONFIG_KEY,
)
from app.services.schwab_account_value import AccountValueResult
from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
from app.services.schwab_client import SchwabClientError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db(client):
    """Open a session against the in-memory test DB the ``client`` fixture
    is bound to. The settings router reads/writes ``app_settings`` rows
    directly, so tests reach in via the dependency-override session too.
    """
    from app.main import app

    override = app.dependency_overrides[get_db]
    return next(override())


def _seed_v1_rules_row(client) -> float:
    """Seed a v1-shape ``rules_config`` row so the next ``load_rules_config``
    triggers the v1 → v2 migration block. Returns the dollar value that the
    migration marker should capture.
    """
    previous_dollars = 5000.0
    stored = DEFAULT_RULES_CONFIG.model_dump()
    # Drop the v2 key and inject the v1 key on the same group — the migration
    # block in rules_config keys off "v1 key present AND v2 key absent".
    stored["position"].pop("sizing_cap_pct", None)
    stored["position"]["sizing_cap_dollars"] = previous_dollars
    # Also drop the schema_version so the row reads as the older shape.
    stored["schema_version"] = 1

    db = _db(client)
    try:
        db.add(AppSetting(key=RULES_CONFIG_KEY, value=json.dumps(stored)))
        db.commit()
    finally:
        db.close()
    return previous_dollars


def _fresh_account_value(total_capital: float = 25000.0) -> AccountValueResult:
    """Build a typical 'ok' AccountValueResult for endpoint round-trip tests."""
    return AccountValueResult(
        status="ok",
        total_capital=total_capital,
        account_id_masked="…4471",
        account_type="CASH",
        accounts=[
            {
                "account_id_masked": "…4471",
                "account_type": "CASH",
                "net_liquidation": total_capital,
            }
        ],
        cached_at=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
    )


def _set_sizing_cap_account(client, value: str | None) -> None:
    """Persist a rules_config row that sets ``position.sizing_cap_account``
    so the account-value endpoints have something to pass through to the
    W-A service.
    """
    stored = DEFAULT_RULES_CONFIG.model_dump()
    stored["position"]["sizing_cap_account"] = value
    db = _db(client)
    try:
        db.add(AppSetting(key=RULES_CONFIG_KEY, value=json.dumps(stored)))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/settings/rules — S4 migration sibling
# ---------------------------------------------------------------------------


class TestRulesEndpointMigration:
    """The GET /rules response carries a ``migration`` sibling (S4)."""

    def test_get_rules_includes_migration_field_when_no_migration_happened(self, client):
        """With no ``sizing_cap_migration`` row, ``migration.sizing_cap`` is None."""
        response = client.get("/api/settings/rules")
        assert response.status_code == 200
        data = response.json()
        assert "migration" in data
        assert data["migration"] == {"sizing_cap": None}

    def test_get_rules_includes_migration_field_after_v1_to_v2_migration(self, client):
        """A v1 row triggers the migration block; GET surfaces the marker."""
        previous_dollars = _seed_v1_rules_row(client)

        # Calling load_rules_config (via any GET) triggers the idempotent
        # v1→v2 migration in rules_config, which writes the marker row.
        response = client.get("/api/settings/rules")
        assert response.status_code == 200
        data = response.json()
        assert "migration" in data
        sizing_cap = data["migration"]["sizing_cap"]
        assert sizing_cap is not None
        assert sizing_cap["previous_sizing_cap_dollars"] == previous_dollars
        assert sizing_cap["dismissed_at"] is None
        # ``migrated_at`` is an ISO8601 string — parse it as a sanity check.
        assert isinstance(sizing_cap["migrated_at"], str)
        datetime.fromisoformat(sizing_cap["migrated_at"])

    def test_dismiss_migration_sets_dismissed_at(self, client):
        """POST dismiss stamps ``dismissed_at``; the next GET surfaces it."""
        _seed_v1_rules_row(client)
        # Trigger the migration by reading rules once.
        client.get("/api/settings/rules")

        resp = client.post("/api/settings/rules/migration/sizing-cap/dismiss")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sizing_cap"] is not None
        first_dismissed = body["sizing_cap"]["dismissed_at"]
        assert isinstance(first_dismissed, str)
        datetime.fromisoformat(first_dismissed)

        # The next GET should reflect the dismissal on the same key.
        got = client.get("/api/settings/rules").json()
        assert got["migration"]["sizing_cap"]["dismissed_at"] == first_dismissed

    def test_dismiss_migration_idempotent(self, client):
        """A second POST is a no-op-success: 200 with a fresh ``dismissed_at``."""
        _seed_v1_rules_row(client)
        client.get("/api/settings/rules")  # trigger migration

        first = client.post("/api/settings/rules/migration/sizing-cap/dismiss")
        assert first.status_code == 200
        first_dismissed = first.json()["sizing_cap"]["dismissed_at"]

        second = client.post("/api/settings/rules/migration/sizing-cap/dismiss")
        assert second.status_code == 200
        second_dismissed = second.json()["sizing_cap"]["dismissed_at"]
        # Implementer's choice (per plan): the second timestamp is the same
        # or strictly later. Either is fine; what matters is that the call
        # didn't 4xx and the field is still populated.
        assert second_dismissed >= first_dismissed

    def test_dismiss_is_safe_when_no_migration_row(self, client):
        """Dismiss on a clean DB returns 200 with ``sizing_cap: null``.

        The UI never asks to dismiss a banner that never existed, but the
        endpoint stays truly idempotent so a stale frontend dispatching a
        dismiss after the row was cleared doesn't 404.
        """
        resp = client.post("/api/settings/rules/migration/sizing-cap/dismiss")
        assert resp.status_code == 200
        assert resp.json() == {"sizing_cap": None}


# ---------------------------------------------------------------------------
# GET/POST /api/settings/account-value — wraps W-A
# ---------------------------------------------------------------------------


class TestAccountValueEndpoints:
    """The account-value endpoints surface W-A's service via the router."""

    def test_get_account_value_returns_cached_when_available(self, client):
        """A fresh hot-cache hit short-circuits — the network function is not called."""
        cached = _fresh_account_value()
        with patch(
            "app.routers.settings.get_cached_account_value",
            return_value=cached,
        ) as mock_cached, patch(
            "app.routers.settings.get_account_value",
        ) as mock_network:
            resp = client.get("/api/settings/account-value")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_capital"] == 25000.0
        assert data["account_id_masked"] == "…4471"
        # ``cached_at`` is serialised as an ISO string.
        assert data["cached_at"] == "2026-05-19T12:00:00+00:00"
        mock_cached.assert_called_once()
        # Cold-cache fall-through must NOT fire when the cache is warm.
        mock_network.assert_not_called()

    def test_get_account_value_falls_through_to_network_when_cache_empty(self, client):
        """On a cold cache, the GET endpoint warms it with one ordinary fetch."""
        fetched = _fresh_account_value(total_capital=37500.0)
        with patch(
            "app.routers.settings.get_cached_account_value",
            return_value=None,
        ) as mock_cached, patch(
            "app.routers.settings.get_account_value",
            return_value=fetched,
        ) as mock_network:
            resp = client.get("/api/settings/account-value")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_capital"] == 37500.0
        mock_cached.assert_called_once()
        mock_network.assert_called_once()
        # The GET fall-through must call get_account_value with
        # force_refresh=False — the POST /refresh endpoint owns the
        # force_refresh=True path.
        _, kwargs = mock_network.call_args
        assert kwargs.get("force_refresh") is False

    def test_post_refresh_calls_force_refresh(self, client):
        """POST /refresh calls get_account_value with ``force_refresh=True``."""
        fetched = _fresh_account_value()
        with patch(
            "app.routers.settings.get_account_value",
            return_value=fetched,
        ) as mock_network:
            resp = client.post("/api/settings/account-value/refresh")

        assert resp.status_code == 200
        mock_network.assert_called_once()
        _, kwargs = mock_network.call_args
        assert kwargs.get("force_refresh") is True

    def test_endpoints_pass_sizing_cap_account_from_rules(self, client):
        """``rules.position.sizing_cap_account`` is threaded into the W-A service."""
        _set_sizing_cap_account(client, "…4471")
        cached = _fresh_account_value()

        with patch(
            "app.routers.settings.get_cached_account_value",
            return_value=cached,
        ) as mock_cached:
            resp = client.get("/api/settings/account-value")
        assert resp.status_code == 200
        _, kwargs = mock_cached.call_args
        assert kwargs.get("sizing_cap_account") == "…4471"

        with patch(
            "app.routers.settings.get_account_value",
            return_value=cached,
        ) as mock_network:
            resp = client.post("/api/settings/account-value/refresh")
        assert resp.status_code == 200
        _, kwargs = mock_network.call_args
        assert kwargs.get("sizing_cap_account") == "…4471"
        assert kwargs.get("force_refresh") is True

    def test_endpoints_return_503_on_schwab_client_error(self, client):
        """A raised :class:`SchwabClientError` is mapped to a generic 503."""
        # GET path: a raise out of get_cached_account_value (defence in
        # depth — the W-A service shouldn't raise, but if it does we must
        # not leak the exception text per CLAUDE.md).
        with patch(
            "app.routers.settings.get_cached_account_value",
            side_effect=SchwabClientError("internal transport text"),
        ):
            resp = client.get("/api/settings/account-value")
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"] == "Schwab service unavailable"
        assert "internal transport text" not in json.dumps(body)

        # POST path: same generic mapping via get_account_value.
        with patch(
            "app.routers.settings.get_account_value",
            side_effect=SchwabClientError("internal transport text"),
        ):
            resp = client.post("/api/settings/account-value/refresh")
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"] == "Schwab service unavailable"
        assert "internal transport text" not in json.dumps(body)

    def test_endpoints_return_503_on_schwab_auth_error(self, client):
        """A raised :class:`SchwabAuthError` is mapped to a generic 503.

        The W-A service translates auth failures into structured
        ``status="disconnected"|"expired"`` results rather than raising,
        but defence-in-depth still requires the router to scrub the raise
        path so a future refactor can't leak the exception text.
        """
        with patch(
            "app.routers.settings.get_cached_account_value",
            side_effect=SchwabAuthError("raw text", code=SchwabAuthCode.TOKEN_EXPIRED),
        ):
            resp = client.get("/api/settings/account-value")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Schwab service unavailable"

    def test_endpoints_return_disconnected_status_in_payload(self, client):
        """``status='disconnected'`` is a structured success — 200, not 503."""
        disconnected = AccountValueResult(
            status="disconnected",
            cached_at=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
            error_detail="Schwab is not connected",
        )

        # GET path — disconnected returned via the cold-cache fall-through.
        with patch(
            "app.routers.settings.get_cached_account_value",
            return_value=None,
        ), patch(
            "app.routers.settings.get_account_value",
            return_value=disconnected,
        ):
            resp = client.get("/api/settings/account-value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disconnected"
        assert data["total_capital"] is None
        assert data["error_detail"] == "Schwab is not connected"

        # POST /refresh path — same contract.
        with patch(
            "app.routers.settings.get_account_value",
            return_value=disconnected,
        ):
            resp = client.post("/api/settings/account-value/refresh")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    def test_get_serialises_cached_at_as_iso_string(self, client):
        """The dataclass ``datetime`` field is surfaced as an ISO string."""
        cached_at = datetime(2026, 4, 1, 9, 30, 0, tzinfo=timezone.utc)
        cached = AccountValueResult(
            status="ok",
            total_capital=10000.0,
            account_id_masked="…0001",
            cached_at=cached_at,
        )
        with patch(
            "app.routers.settings.get_cached_account_value",
            return_value=cached,
        ):
            resp = client.get("/api/settings/account-value")
        assert resp.status_code == 200
        assert resp.json()["cached_at"] == cached_at.isoformat()
