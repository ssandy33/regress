from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from app.services.alpha_vantage_client import (
    get_next_earnings_date,
    clear_cache,
)

# Patch DB cache for all tests — unit tests should not touch SQLite
_NO_DB = patch("app.services.alpha_vantage_client._read_db_cache", return_value=None)
_NO_DB_WRITE = patch("app.services.alpha_vantage_client._write_db_cache")


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the in-memory cache and mock DB cache for each test."""
    clear_cache()
    with _NO_DB, _NO_DB_WRITE:
        yield
    clear_cache()


def _make_csv_response(dates: list[str]) -> str:
    """Build a CSV response like Alpha Vantage returns."""
    lines = ["symbol,name,reportDate,fiscalDateEnding,estimate,currency"]
    for d in dates:
        lines.append(f"AAPL,Apple Inc,{d},2026-03-31,1.50,USD")
    return "\n".join(lines)


def _mock_resp(text: str) -> MagicMock:
    """Build a mock requests.Response with CSV content."""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = text
    resp.headers = {"content-type": "text/csv"}
    resp.raise_for_status = MagicMock()
    return resp


class TestGetNextEarningsDate:
    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_next_future_date(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        future_date = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        past_date = (datetime.now().date() - timedelta(days=10)).strftime("%Y-%m-%d")

        mock_get.return_value = _mock_resp(_make_csv_response([past_date, future_date]))

        result = get_next_earnings_date("AAPL")
        assert result == future_date

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_earliest_future_date(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        date1 = (datetime.now().date() + timedelta(days=30)).strftime("%Y-%m-%d")
        date2 = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")

        mock_get.return_value = _mock_resp(_make_csv_response([date1, date2]))

        result = get_next_earnings_date("AAPL")
        assert result == date2

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_none_when_no_future_dates(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        past_date = (datetime.now().date() - timedelta(days=10)).strftime("%Y-%m-%d")

        mock_get.return_value = _mock_resp(_make_csv_response([past_date]))

        result = get_next_earnings_date("AAPL")
        assert result is None

    def test_returns_none_when_api_key_not_set(self):
        with patch("app.services.alpha_vantage_client.get_alpha_vantage_api_key", return_value=""):
            result = get_next_earnings_date("AAPL")
        assert result is None

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_none_on_api_error(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"
        mock_get.side_effect = Exception("Connection timeout")

        result = get_next_earnings_date("AAPL")
        assert result is None

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_caches_result(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        future_date = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        mock_get.return_value = _mock_resp(_make_csv_response([future_date]))

        result1 = get_next_earnings_date("AAPL")
        result2 = get_next_earnings_date("AAPL")

        assert result1 == result2 == future_date
        assert mock_get.call_count == 1  # Only called once due to cache

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_none_on_empty_csv(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        mock_get.return_value = _mock_resp(
            "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        )

        result = get_next_earnings_date("AAPL")
        assert result is None

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_none_on_missing_report_date_header(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        resp = MagicMock()
        resp.status_code = 200
        resp.text = "symbol,name,fiscalDateEnding\nAAPL,Apple,2026-03-31\n"
        resp.headers = {"content-type": "text/csv"}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = get_next_earnings_date("AAPL")
        assert result is None

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_does_not_cache_transient_failures(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"
        mock_get.side_effect = Exception("timeout")

        result1 = get_next_earnings_date("AAPL")
        assert result1 is None

        # Second call should retry (not served from cache)
        future_date = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        mock_get.side_effect = None
        mock_get.return_value = _mock_resp(_make_csv_response([future_date]))

        result2 = get_next_earnings_date("AAPL")
        assert result2 == future_date

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_detects_json_error_in_200_response(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}
        resp.json.return_value = {"Note": "API rate limit exceeded"}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = get_next_earnings_date("AAPL")
        assert result is None


class TestNoYfinanceImportsAnywhere:
    """Verify yfinance is completely removed from the codebase.

    Comprehensive AST-based check lives in test_acceptance_phase4.py.
    These are smoke tests for the key files.
    """

    def test_no_yfinance_in_options_scanner(self):
        import ast
        import inspect
        import app.services.options_scanner as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "yfinance", "options_scanner.py still imports yfinance"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "yfinance", "options_scanner.py still imports from yfinance"

    def test_no_yfinance_in_regression_router(self):
        import ast
        import inspect
        import app.routers.regression as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "yfinance", "regression.py still imports yfinance"
            if isinstance(node, ast.ImportFrom):
                if node.module and "yfinance" in node.module:
                    raise AssertionError("regression.py still imports from yfinance")

    def test_no_yfinance_in_health_router(self):
        import ast
        import inspect
        import app.routers.health as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "yfinance", "health.py still imports yfinance"
            if isinstance(node, ast.ImportFrom):
                if node.module and "yfinance" in node.module:
                    raise AssertionError("health.py still imports from yfinance")
