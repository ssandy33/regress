"""Unit tests for the pre-start Schwab-token scrub (root-cause fix for #379).

The scrub runs from a one-off container BEFORE ``compose up -d`` so the backend
can boot even when stale ``schwab_*`` tokens sit in the persistent QA volume
without ``SCHWAB_ENCRYPTION_KEY`` (the #380 ``seed_qa`` scrub can't help — it
runs via ``compose exec`` into a container that the very tokens prevent from
starting; see ``scripts/scrub_schwab_tokens`` module docstring).

These tests drive the pure function against throwaway SQLite files (no FastAPI
app, no TestClient, no conftest session, no network) — ``@pytest.mark.unit``,
matching the repo precedent for ``scripts/*`` helper tests (e.g.
``test_reconcile_positions``).
"""

from __future__ import annotations

import sqlite3

import pytest

from app.services.encryption import ENCRYPTED_SETTING_KEYS
from scripts.scrub_schwab_tokens import main, scrub_schwab_tokens


def _make_db(path, settings):
    """Create a SQLite DB with an ``app_settings`` table seeded from ``settings``."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.executemany(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        list(settings.items()),
    )
    conn.commit()
    conn.close()


def _keys(path):
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT key FROM app_settings")}
    finally:
        conn.close()


@pytest.mark.unit
def test_scrubs_all_sensitive_token_keys(tmp_path):
    db = tmp_path / "regression_tool.db"
    seeded = {k: "secret" for k in ENCRYPTED_SETTING_KEYS}
    _make_db(db, seeded)

    deleted = scrub_schwab_tokens(str(db))

    assert deleted == len(ENCRYPTED_SETTING_KEYS)
    assert _keys(str(db)) == set()


@pytest.mark.unit
def test_preserves_non_sensitive_settings(tmp_path):
    db = tmp_path / "regression_tool.db"
    _make_db(
        db,
        {
            "schwab_access_token": "a",
            "schwab_refresh_token": "r",
            "schwab_app_key": "k",
            "schwab_app_secret": "s",
            # Non-sensitive schwab rows + an unrelated setting MUST survive:
            # they don't trip the startup security check.
            "schwab_access_token_expires": "2026-01-01",
            "schwab_account_value:__default__": "1000",
            "nextauth_secret": "keep-me",
        },
    )

    deleted = scrub_schwab_tokens(str(db))

    assert deleted == 4
    assert _keys(str(db)) == {
        "schwab_access_token_expires",
        "schwab_account_value:__default__",
        "nextauth_secret",
    }


@pytest.mark.unit
def test_key_list_matches_security_check_source_of_truth(tmp_path):
    """The scrub must delete exactly the keys the startup check trips on —
    binding it to ENCRYPTED_SETTING_KEYS so the two can never drift."""
    db = tmp_path / "regression_tool.db"
    # One row per sensitive key plus a decoy that looks schwab-ish but isn't
    # in the trip list.
    seeded = {k: "v" for k in ENCRYPTED_SETTING_KEYS}
    seeded["schwab_refresh_token_expires"] = "2026-01-01"
    _make_db(db, seeded)

    scrub_schwab_tokens(str(db))

    assert _keys(str(db)) == {"schwab_refresh_token_expires"}


@pytest.mark.unit
def test_idempotent_second_run_deletes_zero(tmp_path):
    db = tmp_path / "regression_tool.db"
    _make_db(db, {k: "v" for k in ENCRYPTED_SETTING_KEYS})

    assert scrub_schwab_tokens(str(db)) == len(ENCRYPTED_SETTING_KEYS)
    assert scrub_schwab_tokens(str(db)) == 0


@pytest.mark.unit
def test_missing_app_settings_table_is_a_noop(tmp_path):
    """A fresh QA volume has the DB file but no tables yet (init_db runs at
    backend startup, AFTER this pre-start scrub). That must be a clean no-op,
    not a crash."""
    db = tmp_path / "regression_tool.db"
    sqlite3.connect(db).close()  # empty DB file, no app_settings table

    assert scrub_schwab_tokens(str(db)) == 0


@pytest.mark.unit
def test_empty_app_settings_table_is_a_noop(tmp_path):
    db = tmp_path / "regression_tool.db"
    _make_db(db, {})

    assert scrub_schwab_tokens(str(db)) == 0


@pytest.mark.unit
def test_main_cli_scrubs_and_reports(tmp_path, capsys):
    db = tmp_path / "regression_tool.db"
    _make_db(db, {k: "v" for k in ENCRYPTED_SETTING_KEYS})

    rc = main([str(db)])

    assert rc == 0
    out = capsys.readouterr().out
    assert f"Scrubbed {len(ENCRYPTED_SETTING_KEYS)} Schwab token row(s)" in out
    assert _keys(str(db)) == set()
