from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from app.models.database import CacheEntry


def _insert_cache_entry(client, asset_key, source_name="fred",
                        frequency="daily", data='{"value": [1,2,3]}',
                        fetched_at=None):
    """Insert a CacheEntry via the test DB session."""
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc).isoformat()
    from app.models.database import get_db
    from app.main import app
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    entry = CacheEntry(
        asset_key=asset_key,
        source_name=source_name,
        source_frequency=frequency,
        data=data,
        fetched_at=fetched_at,
    )
    db.add(entry)
    db.commit()
    return entry


class TestSettingsEndpoints:
    """Tests for core settings CRUD endpoints."""

    def test_get_settings(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "fred_api_key_set" in data
        assert "cache_ttl_daily_hours" in data
        assert "theme" in data

    def test_update_setting(self, client):
        response = client.put("/api/settings", json={"key": "theme", "value": "dark"})
        assert response.status_code == 200
        assert response.json()["key"] == "theme"
        get_resp = client.get("/api/settings")
        assert get_resp.json()["theme"] == "dark"

    def test_get_cache_stats_empty(self, client):
        response = client.get("/api/settings/cache")
        assert response.status_code == 200
        data = response.json()
        assert data["entry_count"] == 0
        assert data["total_size_bytes"] == 0


class TestCacheClearAndFreshness:
    """Tests for DELETE /api/settings/cache and GET /api/settings/cache/freshness."""

    def test_clear_cache_empty(self, client):
        """Clearing an empty cache succeeds with status ok."""
        response = client.delete("/api/settings/cache")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["message"] == "Cache cleared"

    def test_clear_cache_with_entries(self, client):
        """Clearing a populated cache removes all entries."""
        _insert_cache_entry(client, "fred:DGS10")
        _insert_cache_entry(client, "schwab:AAPL", source_name="schwab")

        # Verify entries exist
        stats = client.get("/api/settings/cache").json()
        assert stats["entry_count"] == 2

        # Clear and verify
        response = client.delete("/api/settings/cache")
        assert response.status_code == 200

        stats_after = client.get("/api/settings/cache").json()
        assert stats_after["entry_count"] == 0

    def test_cache_freshness_empty(self, client):
        """No cache entries returns empty entries list."""
        response = client.get("/api/settings/cache/freshness")
        assert response.status_code == 200
        data = response.json()
        assert data["entries"] == []

    def test_cache_freshness_fresh_entry(self, client):
        """Entry fetched 5 days ago is labeled 'fresh'."""
        fetched_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        _insert_cache_entry(client, "fred:DGS10", fetched_at=fetched_at)

        response = client.get("/api/settings/cache/freshness")
        assert response.status_code == 200
        entries = response.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["freshness"] == "fresh"
        assert entries[0]["age_days"] == 5
        assert entries[0]["asset_key"] == "fred:DGS10"

    def test_cache_freshness_stale_entry(self, client):
        """Entry fetched 60 days ago is labeled 'stale'."""
        fetched_at = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _insert_cache_entry(client, "fred:DGS10", fetched_at=fetched_at)

        response = client.get("/api/settings/cache/freshness")
        entries = response.json()["entries"]
        assert entries[0]["freshness"] == "stale"
        assert entries[0]["age_days"] == 60

    def test_cache_freshness_very_stale_entry(self, client):
        """Entry fetched 100 days ago is labeled 'very_stale'."""
        fetched_at = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        _insert_cache_entry(client, "fred:DGS10", fetched_at=fetched_at)

        response = client.get("/api/settings/cache/freshness")
        entries = response.json()["entries"]
        assert entries[0]["freshness"] == "very_stale"
        assert entries[0]["age_days"] == 100

    def test_cache_freshness_naive_datetime(self, client):
        """Naive datetime (no tzinfo) is treated as UTC."""
        fetched_at = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        _insert_cache_entry(client, "fred:DGS10", fetched_at=fetched_at)

        response = client.get("/api/settings/cache/freshness")
        entries = response.json()["entries"]
        assert entries[0]["freshness"] == "fresh"
        assert entries[0]["age_days"] == 10


class TestHealthChecks:
    """Tests for GET /api/settings/health/fred and /health/schwab."""

    def test_fred_health_no_key(self, client):
        """No FRED key returns configured=False, valid=False."""
        with patch("app.routers.settings.get_fred_api_key", return_value=None):
            response = client.get("/api/settings/health/fred")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["valid"] is False

    def test_fred_health_valid_key(self, client):
        """Valid FRED key returns configured=True, valid=True."""
        mock_fred_cls = MagicMock()
        with patch("app.routers.settings.get_fred_api_key", return_value="test-key"), \
             patch("app.routers.settings.Fred", mock_fred_cls, create=True), \
             patch.dict("sys.modules", {"fredapi": MagicMock(Fred=mock_fred_cls)}):
            response = client.get("/api/settings/health/fred")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is True

    def test_fred_health_invalid_key(self, client):
        """Invalid FRED key returns configured=True, valid=False."""
        mock_fred_cls = MagicMock()
        mock_fred_cls.return_value.get_series.side_effect = ValueError("Bad key")
        with patch("app.routers.settings.get_fred_api_key", return_value="bad-key"), \
             patch.dict("sys.modules", {"fredapi": MagicMock(Fred=mock_fred_cls)}):
            response = client.get("/api/settings/health/fred")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is False

    def test_schwab_health_not_configured(self, client):
        """No Schwab tokens returns configured=False."""
        with patch("app.routers.settings.SchwabTokenManager") as mock_cls:
            mock_cls.return_value.is_configured.return_value = False
            response = client.get("/api/settings/health/schwab")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["valid"] is False

    def test_schwab_health_configured_valid(self, client):
        """Configured Schwab with valid token returns valid=True."""
        expiry = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("app.routers.settings.SchwabTokenManager") as mock_cls, \
             patch("httpx.get", return_value=mock_resp):
            mgr = mock_cls.return_value
            mgr.is_configured.return_value = True
            mgr.get_refresh_token_expiry.return_value = expiry
            mgr.get_access_token.return_value = "test-token"

            response = client.get("/api/settings/health/schwab")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["token_expiry"] is not None
        assert data["token_expiry"]["warning"] is False
        assert data["token_expiry"]["expired"] is False

    def test_schwab_health_expired_token(self, client):
        """Expired Schwab token returns valid=False with sanitized error."""
        with patch("app.routers.settings.SchwabTokenManager") as mock_cls:
            mgr = mock_cls.return_value
            mgr.is_configured.return_value = True
            mgr.get_refresh_token_expiry.return_value = None
            mgr.get_access_token.side_effect = Exception("Token expired")

            response = client.get("/api/settings/health/schwab")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert data["error"] == "Validation failed"
        # Verify raw exception message is NOT leaked
        assert "Token expired" not in str(data)

    def test_schwab_health_http_error(self, client):
        """Schwab API HTTP error returns valid=False with HTTP status."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )
        with patch("app.routers.settings.SchwabTokenManager") as mock_cls, \
             patch("httpx.get", return_value=mock_response):
            mgr = mock_cls.return_value
            mgr.is_configured.return_value = True
            mgr.get_refresh_token_expiry.return_value = None
            mgr.get_access_token.return_value = "test-token"

            response = client.get("/api/settings/health/schwab")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert data["error"] == "HTTP 401"


class TestBackups:
    """Tests for GET /api/settings/backups and POST /api/settings/backups/restore."""

    def test_list_backups_empty(self, client):
        """No backups returns empty list."""
        with patch("app.routers.settings.list_backups", return_value=[]):
            response = client.get("/api/settings/backups")
        assert response.status_code == 200
        assert response.json()["backups"] == []

    def test_list_backups_with_entries(self, client):
        """Backups list returns proper structure."""
        sample_backups = [
            {"filename": "regression_tool_20240601_120000.db",
             "size_bytes": 4096,
             "created_at": "2024-06-01T12:00:00"},
            {"filename": "regression_tool_20240530_080000.db",
             "size_bytes": 3072,
             "created_at": "2024-05-30T08:00:00"},
        ]
        with patch("app.routers.settings.list_backups", return_value=sample_backups):
            response = client.get("/api/settings/backups")
        assert response.status_code == 200
        data = response.json()
        assert len(data["backups"]) == 2
        assert data["backups"][0]["filename"] == "regression_tool_20240601_120000.db"

    def test_restore_success(self, client):
        """Successful restore returns status ok."""
        with patch("app.routers.settings.restore_backup") as mock_restore:
            response = client.post(
                "/api/settings/backups/restore",
                params={"filename": "regression_tool_20240601_120000.db"},
            )
            mock_restore.assert_called_once_with("regression_tool_20240601_120000.db")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "Restored" in data["message"]

    def test_restore_not_found(self, client):
        """Restoring a nonexistent backup returns 404."""
        with patch(
            "app.routers.settings.restore_backup",
            side_effect=FileNotFoundError("Backup not found"),
        ):
            response = client.post(
                "/api/settings/backups/restore",
                params={"filename": "nonexistent.db"},
            )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_restore_failure_sanitized_error(self, client):
        """Generic restore failure returns 500 with sanitized message."""
        with patch(
            "app.routers.settings.restore_backup",
            side_effect=Exception("disk I/O error on sector 42"),
        ):
            response = client.post(
                "/api/settings/backups/restore",
                params={"filename": "regression_tool_20240601_120000.db"},
            )
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail == "Backup restore failed"
        # Verify raw exception is NOT leaked
        assert "disk I/O" not in detail


class TestCacheRefresh:
    """Tests for POST /api/settings/cache/refresh-all and /cache/refresh-stale."""

    def test_refresh_all_empty(self, client):
        """No cache entries returns empty results."""
        response = client.post("/api/settings/cache/refresh-all")
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_refresh_all_with_entries(self, client, mock_fetcher):
        """All entries are refreshed successfully."""
        _insert_cache_entry(client, "fred:DGS10")
        _insert_cache_entry(client, "schwab:AAPL", source_name="schwab")

        response = client.post("/api/settings/cache/refresh-all")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 2
        assert all(r["status"] == "refreshed" for r in results)

    def test_refresh_all_skips_zillow_csv(self, client, mock_fetcher):
        """The zillow:__csv__ entry is skipped during refresh-all."""
        _insert_cache_entry(client, "zillow:__csv__", source_name="zillow")
        _insert_cache_entry(client, "fred:DGS10")

        response = client.post("/api/settings/cache/refresh-all")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["asset_key"] == "fred:DGS10"

    def test_refresh_all_partial_failure(self, client):
        """Mixed success/failure returns per-entry status with sanitized errors."""
        _insert_cache_entry(client, "fred:DGS10")
        _insert_cache_entry(client, "fred:CPIAUCSL")

        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Connection timed out")
            import pandas as pd
            return pd.DataFrame({"value": [1]}, index=pd.date_range("2023-01-01", periods=1)), MagicMock()

        with patch("app.services.data_fetcher.DataFetcher.fetch", side_effect=_side_effect):
            response = client.post("/api/settings/cache/refresh-all")

        results = response.json()["results"]
        assert len(results) == 2
        failed = [r for r in results if r["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["error"] == "Refresh failed"
        # Verify raw exception is NOT leaked
        assert "Connection timed out" not in str(results)

    def test_refresh_stale_no_stale_entries(self, client):
        """All entries are fresh (<30 days), none are refreshed."""
        fetched_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        _insert_cache_entry(client, "fred:DGS10", fetched_at=fetched_at)

        response = client.post("/api/settings/cache/refresh-stale")
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_refresh_stale_with_stale_entries(self, client, mock_fetcher):
        """Only stale entries (>30 days) are refreshed."""
        fresh_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        stale_at = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _insert_cache_entry(client, "fred:DGS10", fetched_at=fresh_at)
        _insert_cache_entry(client, "fred:CPIAUCSL", fetched_at=stale_at)

        response = client.post("/api/settings/cache/refresh-stale")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["asset_key"] == "fred:CPIAUCSL"
        assert results[0]["status"] == "refreshed"

    def test_refresh_stale_skips_zillow_csv(self, client, mock_fetcher):
        """The zillow:__csv__ entry is skipped even when stale."""
        stale_at = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _insert_cache_entry(client, "zillow:__csv__", source_name="zillow",
                            fetched_at=stale_at)
        _insert_cache_entry(client, "fred:DGS10", fetched_at=stale_at)

        response = client.post("/api/settings/cache/refresh-stale")
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["asset_key"] == "fred:DGS10"
