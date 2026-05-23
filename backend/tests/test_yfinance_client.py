"""Tests for the yfinance client wrapper (issues #287, #288).

Covers:

- #287: CookieCache directory configuration at module import time, env
  var override path, default ``/tmp/yfinance-cache``, and the
  ``set_tz_cache_location`` invocation.
- #288: the rate-limit classifier (``_classify_yfinance_error``) and
  the narrowed-except behavior on the two fetcher functions.

The yfinance library is never actually called over the network — tests
pass ``env_override`` to :func:`_configure_yfinance_cache_dir` so the
side effect (``makedirs`` + ``set_tz_cache_location``) is observed
without ``importlib.reload`` magic. The fetcher tests patch
``yfinance.Ticker`` to raise the documented HTML-as-JSON rate-limit
signature.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.services import yfinance_client
from app.services.yfinance_client import YFinanceRateLimitedError


def test_cache_dir_is_configured_on_module_import():
    """``YFINANCE_CACHE_DIR`` is set at module import and points to a real path."""
    assert isinstance(yfinance_client.YFINANCE_CACHE_DIR, str)
    assert yfinance_client.YFINANCE_CACHE_DIR != ""


def test_cache_dir_default_is_tmp_when_env_unset(monkeypatch):
    """No env var → default ``/tmp/yfinance-cache``."""
    monkeypatch.delenv("YFINANCE_CACHE_DIR", raising=False)
    with patch("yfinance.set_tz_cache_location") as set_loc:
        result = yfinance_client._configure_yfinance_cache_dir()

    assert result == "/tmp/yfinance-cache"
    assert os.path.isdir("/tmp/yfinance-cache")
    set_loc.assert_called_once_with("/tmp/yfinance-cache")


def test_env_var_override_picks_up_custom_dir(monkeypatch, tmp_path):
    """``YFINANCE_CACHE_DIR`` env var overrides the default."""
    target = tmp_path / "yfin"
    monkeypatch.setenv("YFINANCE_CACHE_DIR", str(target))
    with patch("yfinance.set_tz_cache_location") as set_loc:
        result = yfinance_client._configure_yfinance_cache_dir()

    assert result == str(target)
    assert target.is_dir()
    set_loc.assert_called_once_with(str(target))


def test_explicit_env_override_arg_bypasses_environ(tmp_path):
    """``env_override`` parameter is honored without consulting the environment."""
    target = tmp_path / "explicit"
    with patch("yfinance.set_tz_cache_location") as set_loc:
        result = yfinance_client._configure_yfinance_cache_dir(
            env_override=str(target)
        )

    assert result == str(target)
    assert target.is_dir()
    set_loc.assert_called_once_with(str(target))


# ---------------------------------------------------------------------------
# Issue #288 — rate-limit classification + narrowed except
# ---------------------------------------------------------------------------


def test_json_decode_error_expecting_value_classified_as_rate_limit():
    """The Yahoo HTML-as-JSON signature → YFinanceRateLimitedError."""
    exc = json.JSONDecodeError(
        "Expecting value: line 1 column 1 (char 0)", "<!DOCTYPE html>", 0
    )
    result = yfinance_client._classify_yfinance_error(exc)
    assert isinstance(result, YFinanceRateLimitedError)


def test_other_json_decode_error_propagated_unchanged():
    """Different JSONDecodeError messages pass through unchanged."""
    exc = json.JSONDecodeError(
        "Extra data: line 2 column 1 (char 5)", "x", 5
    )
    result = yfinance_client._classify_yfinance_error(exc)
    assert result is exc


def test_non_json_decode_error_propagated_unchanged():
    """Any non-JSONDecodeError exception passes through unchanged."""
    exc = ValueError("nope")
    result = yfinance_client._classify_yfinance_error(exc)
    assert result is exc


def test_fetch_business_info_raises_rate_limit_on_html_429():
    """fetch_business_info re-raises YFinanceRateLimitedError on the 429 signature."""
    fake_ticker = MagicMock()
    type(fake_ticker).info = property(
        lambda self: (_ for _ in ()).throw(
            json.JSONDecodeError(
                "Expecting value: line 1 column 1 (char 0)",
                "<!DOCTYPE html>",
                0,
            )
        )
    )
    with patch("yfinance.Ticker", return_value=fake_ticker):
        with pytest.raises(YFinanceRateLimitedError):
            yfinance_client.fetch_business_info("SOFI")


def test_fetch_quarterly_income_stmt_raises_rate_limit_on_html_429():
    """fetch_quarterly_income_stmt re-raises YFinanceRateLimitedError on the 429 signature."""
    fake_ticker = MagicMock()
    type(fake_ticker).quarterly_income_stmt = property(
        lambda self: (_ for _ in ()).throw(
            json.JSONDecodeError(
                "Expecting value: line 1 column 1 (char 0)",
                "<!DOCTYPE html>",
                0,
            )
        )
    )
    with patch("yfinance.Ticker", return_value=fake_ticker):
        with pytest.raises(YFinanceRateLimitedError):
            yfinance_client.fetch_quarterly_income_stmt("SOFI", 8)


def test_fetch_business_info_returns_none_on_other_failure():
    """Non-classified failure still returns None (existing contract)."""
    fake_ticker = MagicMock()
    type(fake_ticker).info = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("transient"))
    )
    with patch("yfinance.Ticker", return_value=fake_ticker):
        assert yfinance_client.fetch_business_info("SOFI") is None
