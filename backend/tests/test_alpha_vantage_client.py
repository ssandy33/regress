from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from app.services.alpha_vantage_client import (
    get_next_earnings_date,
    clear_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the in-memory cache before each test."""
    clear_cache()
    yield
    clear_cache()


def _make_csv_response(dates: list[str]) -> str:
    """Build a CSV response like Alpha Vantage returns."""
    lines = ["symbol,name,reportDate,fiscalDateEnding,estimate,currency"]
    for d in dates:
        lines.append(f"AAPL,Apple Inc,{d},2026-03-31,1.50,USD")
    return "\n".join(lines)


class TestGetNextEarningsDate:
    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_next_future_date(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        future_date = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        past_date = (datetime.now().date() - timedelta(days=10)).strftime("%Y-%m-%d")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_csv_response([past_date, future_date])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_next_earnings_date("AAPL")
        assert result == future_date

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_earliest_future_date(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        date1 = (datetime.now().date() + timedelta(days=30)).strftime("%Y-%m-%d")
        date2 = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_csv_response([date1, date2])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_next_earnings_date("AAPL")
        assert result == date2

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_none_when_no_future_dates(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        past_date = (datetime.now().date() - timedelta(days=10)).strftime("%Y-%m-%d")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_csv_response([past_date])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_next_earnings_date("AAPL")
        assert result is None

    @patch("app.services.alpha_vantage_client.settings")
    def test_returns_none_when_api_key_not_set(self, mock_settings):
        mock_settings.alpha_vantage_api_key = ""

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
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_csv_response([future_date])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result1 = get_next_earnings_date("AAPL")
        result2 = get_next_earnings_date("AAPL")

        assert result1 == result2 == future_date
        assert mock_get.call_count == 1  # Only called once due to cache

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_returns_none_on_empty_csv(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_next_earnings_date("AAPL")
        assert result is None


class TestNoYfinanceImportsAnywhere:
    """Verify yfinance is completely removed from the codebase."""

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
