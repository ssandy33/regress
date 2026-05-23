"""Tests for the yfinance client wrapper (issues #287, #288).

Covers:

- #287: CookieCache directory configuration at module import time, env
  var override path, default ``/tmp/yfinance-cache``, and the
  ``set_tz_cache_location`` invocation.
- #288 (appended in a later commit): the rate-limit classifier and the
  narrowed-except behavior on the two fetcher functions.

The yfinance library is never actually called over the network — tests
pass ``env_override`` to :func:`_configure_yfinance_cache_dir` so the
side effect (``makedirs`` + ``set_tz_cache_location``) is observed
without ``importlib.reload`` magic.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from app.services import yfinance_client


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
