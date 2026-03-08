"""Acceptance tests for Phase 4: Earnings Dates via Alpha Vantage + Remove yfinance.

Maps directly to acceptance criteria from issue #8.
"""

import ast
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.services.alpha_vantage_client import get_next_earnings_date, clear_cache


BACKEND_APP_DIR = Path(__file__).resolve().parent.parent / "app"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clear_av_cache():
    clear_cache()
    with patch("app.services.alpha_vantage_client._read_db_cache", return_value=None), \
         patch("app.services.alpha_vantage_client._write_db_cache"):
        yield
    clear_cache()


class TestAC1_EarningsDatesResolveViaAlphaVantage:
    """AC: Earnings dates resolve correctly via Alpha Vantage."""

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_parses_csv_and_returns_next_future_date(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        future = (datetime.now().date() + timedelta(days=15)).strftime("%Y-%m-%d")
        csv_text = (
            "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
            f"AAPL,Apple Inc,{future},2026-03-31,1.50,USD\n"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_next_earnings_date("AAPL")

        assert result == future
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["function"] == "EARNINGS_CALENDAR"
        assert kwargs["params"]["symbol"] == "AAPL"

    @patch("app.services.alpha_vantage_client.settings")
    @patch("app.services.alpha_vantage_client.requests.get")
    def test_selects_earliest_future_date_from_multiple(self, mock_get, mock_settings):
        mock_settings.alpha_vantage_api_key = "test_key"

        early = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        late = (datetime.now().date() + timedelta(days=90)).strftime("%Y-%m-%d")
        csv_text = (
            "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
            f"AAPL,Apple Inc,{late},2026-06-30,1.60,USD\n"
            f"AAPL,Apple Inc,{early},2026-03-31,1.50,USD\n"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_next_earnings_date("AAPL")
        assert result == early


class TestAC2_EarningsExclusionWorksInScanner:
    """AC: Earnings exclusion still works in scanner when date is available."""

    @patch("app.services.options_scanner.get_next_earnings_date")
    @patch("app.services.options_scanner.SchwabClient")
    def test_scan_excludes_expirations_near_earnings(self, mock_client_cls, mock_earnings):
        from app.models.schemas import OptionScanRequest
        from app.services.options_scanner import OptionScanner

        scanner = OptionScanner()
        today = datetime.now().date()

        # Earnings in 32 days — with exclude_earnings_dte=5, expirations within 5 days of earnings are excluded
        earnings_date = (today + timedelta(days=32)).strftime("%Y-%m-%d")
        mock_earnings.return_value = earnings_date

        # Two expirations: 30 days (within 5 of earnings) and 45 days (safe)
        exp_near = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        exp_safe = (today + timedelta(days=45)).strftime("%Y-%m-%d")

        chain_resp = {
            "symbol": "TEST",
            "status": "SUCCESS",
            "underlying": {"last": 100.0, "close": 100.0,
                           "fiftyTwoWeekHigh": 130.0, "fiftyTwoWeekLow": 70.0,
                           "totalVolume": 5000000},
            "putExpDateMap": {
                f"{exp_near}:30": {
                    "90.0": [{"strikePrice": 90.0, "bid": 1.0, "ask": 1.2, "mark": 1.1,
                              "delta": -0.25, "gamma": 0.02, "theta": -0.03, "vega": 0.05,
                              "openInterest": 500, "totalVolume": 100, "volatility": 30.0}],
                },
                f"{exp_safe}:45": {
                    "90.0": [{"strikePrice": 90.0, "bid": 1.5, "ask": 1.7, "mark": 1.6,
                              "delta": -0.25, "gamma": 0.02, "theta": -0.03, "vega": 0.05,
                              "openInterest": 500, "totalVolume": 100, "volatility": 30.0}],
                },
            },
            "callExpDateMap": {},
        }

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 18.5}

        req = OptionScanRequest(
            ticker="TEST",
            strategy="cash_secured_put",
            capital_available=10000.0,
            min_dte=25,
            max_dte=50,
            min_return_pct=0.1,
            exclude_earnings_dte=5,
        )

        result = scanner.scan(req)

        # Only the safe expiration should produce recommendations
        assert result["earnings_date"] == earnings_date
        expirations = [r.expiration for r in result["recommendations"]]
        assert exp_near not in expirations
        assert exp_safe in expirations


class TestAC3_ScannerCompletesWhenAlphaVantageReturnsNone:
    """AC: Scanner completes successfully when Alpha Vantage returns None."""

    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_scan_succeeds_with_none_earnings(self, mock_client_cls, _mock_earnings):
        from app.models.schemas import OptionScanRequest
        from app.services.options_scanner import OptionScanner

        scanner = OptionScanner()
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        chain_resp = {
            "symbol": "TEST",
            "status": "SUCCESS",
            "underlying": {"last": 100.0, "close": 100.0,
                           "fiftyTwoWeekHigh": 130.0, "fiftyTwoWeekLow": 70.0,
                           "totalVolume": 5000000},
            "putExpDateMap": {
                f"{exp_date}:{dte}": {
                    "90.0": [{"strikePrice": 90.0, "bid": 1.0, "ask": 1.2, "mark": 1.1,
                              "delta": -0.25, "gamma": 0.02, "theta": -0.03, "vega": 0.05,
                              "openInterest": 500, "totalVolume": 100, "volatility": 30.0}],
                },
            },
            "callExpDateMap": {},
        }

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 18.5}

        req = OptionScanRequest(
            ticker="TEST",
            strategy="cash_secured_put",
            capital_available=10000.0,
            min_dte=25,
            max_dte=50,
            min_return_pct=0.1,
        )

        result = scanner.scan(req)

        assert result["earnings_date"] is None
        assert len(result["recommendations"]) >= 1


class TestAC4_YfinanceRemovedFromRequirements:
    """AC: yfinance fully removed from requirements.txt."""

    def test_requirements_has_no_yfinance(self):
        requirements_path = BACKEND_ROOT / "requirements.txt"
        content = requirements_path.read_text()
        assert "yfinance" not in content, "yfinance still present in requirements.txt"


class TestAC5_NoYfinanceImportsInAnyFile:
    """AC: No remaining yfinance imports in any file (verified by CI)."""

    def test_no_yfinance_imports_in_any_python_file(self):
        """Walk all .py files under backend/app/ and assert no yfinance imports."""
        violations = []
        for py_file in BACKEND_APP_DIR.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "yfinance":
                            violations.append(f"{py_file.relative_to(BACKEND_ROOT)}: import yfinance")
                if isinstance(node, ast.ImportFrom):
                    if node.module and "yfinance" in node.module:
                        violations.append(f"{py_file.relative_to(BACKEND_ROOT)}: from {node.module}")

        assert violations == [], "yfinance imports found:\n" + "\n".join(violations)

    def test_no_yf_name_references_in_source(self):
        """No 'yf.' usage pattern in any source file."""
        violations = []
        for py_file in BACKEND_APP_DIR.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "yf":
                    violations.append(f"{py_file.relative_to(BACKEND_ROOT)}: 'yf' name reference")

        assert violations == [], "yf references found:\n" + "\n".join(violations)


class TestAC6_EnvExampleDocumentsAllVars:
    """AC: .env.example documents all 4 new env vars with setup instructions."""

    def test_env_example_has_required_vars(self):
        env_example_path = BACKEND_ROOT.parent / ".env.example"
        content = env_example_path.read_text()

        required_vars = [
            "FRED_API_KEY",
            "SCHWAB_APP_KEY",
            "SCHWAB_APP_SECRET",
            "ALPHA_VANTAGE_API_KEY",
        ]
        for var in required_vars:
            assert var in content, f"{var} not found in .env.example"
