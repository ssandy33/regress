"""Tests for the shared AppSetting cache helpers (issue #284).

Covers :func:`app.services.research_cache_utils.read_app_setting` and
:func:`app.services.research_cache_utils.write_app_setting` — the
deduplicated helpers extracted from research_business and
research_financials. Test surface focuses on:

- happy-path roundtrip (write then read returns the same payload + ts)
- missing-key returns ``None``
- malformed value (missing pipe separator) returns ``None``
- non-dict JSON payload returns ``None``
- invalid ISO-8601 timestamp returns ``None``
- second write upserts (no duplicate row)
"""

from __future__ import annotations
import pytest

import json
from datetime import datetime, timezone

from app.models.database import AppSetting
from app.services.research_cache_utils import (
    read_app_setting,
    write_app_setting,
)


def _db_session(client):
    """Pull a session bound to the in-memory test DB."""
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    return next(override())


@pytest.mark.integration
def test_roundtrip_read_after_write_returns_payload_and_timestamp(client):
    """Happy path — write then read returns the exact payload + timestamp."""
    db = _db_session(client)
    payload = {"ticker": "SOFI", "name": "SoFi Technologies, Inc."}
    fetched_at = datetime(2026, 5, 22, 17, 30, 0, tzinfo=timezone.utc)

    write_app_setting(db, "yf_business:SOFI", payload, fetched_at)
    result = read_app_setting(db, "yf_business:SOFI")

    assert result is not None
    persisted_payload, persisted_ts = result
    assert persisted_payload == payload
    assert persisted_ts == fetched_at


@pytest.mark.integration
def test_read_returns_none_for_missing_key(client):
    """No row for the key → ``None``, no exception."""
    db = _db_session(client)
    assert read_app_setting(db, "yf_business:NOPE") is None


@pytest.mark.integration
def test_read_returns_none_for_malformed_value_no_pipe(client):
    """Value without the ``|`` separator → ``None`` (defensive)."""
    db = _db_session(client)
    db.add(AppSetting(key="yf_business:BAD", value="no-pipe-here"))
    db.commit()

    assert read_app_setting(db, "yf_business:BAD") is None


@pytest.mark.integration
def test_read_returns_none_for_non_dict_payload(client):
    """JSON list payload → ``None`` (the contract is dict-only)."""
    db = _db_session(client)
    fetched_at = datetime(2026, 5, 22, 17, 30, 0, tzinfo=timezone.utc)
    db.add(
        AppSetting(
            key="yf_business:LIST",
            value=f"{fetched_at.isoformat()}|{json.dumps([1, 2, 3])}",
        )
    )
    db.commit()

    assert read_app_setting(db, "yf_business:LIST") is None


@pytest.mark.integration
def test_read_returns_none_for_invalid_timestamp(client):
    """Unparseable ISO timestamp → ``None`` (caller falls through to fetch)."""
    db = _db_session(client)
    db.add(
        AppSetting(
            key="yf_business:BADTS",
            value=f"not-a-date|{json.dumps({'ticker': 'SOFI'})}",
        )
    )
    db.commit()

    assert read_app_setting(db, "yf_business:BADTS") is None


@pytest.mark.integration
def test_write_upserts_existing_key(client):
    """Second write to the same key replaces the row — no duplicate inserts."""
    db = _db_session(client)
    fetched_at_v1 = datetime(2026, 5, 22, 17, 30, 0, tzinfo=timezone.utc)
    fetched_at_v2 = datetime(2026, 5, 23, 17, 30, 0, tzinfo=timezone.utc)

    write_app_setting(db, "yf_business:SOFI", {"v": 1}, fetched_at_v1)
    write_app_setting(db, "yf_business:SOFI", {"v": 2}, fetched_at_v2)

    rows = (
        db.query(AppSetting)
        .filter(AppSetting.key == "yf_business:SOFI")
        .all()
    )
    assert len(rows) == 1
    result = read_app_setting(db, "yf_business:SOFI")
    assert result is not None
    persisted_payload, persisted_ts = result
    assert persisted_payload == {"v": 2}
    assert persisted_ts == fetched_at_v2


@pytest.mark.integration
def test_write_swallows_typeerror_on_non_serializable_payload(client):
    """Non-JSON-serializable payload (set) raises ``TypeError`` inside
    ``json.dumps`` — helper must catch it per the "never propagate"
    contract (CodeRabbit PR #289). The row must NOT be created.
    """
    db = _db_session(client)
    fetched_at = datetime(2026, 5, 23, 17, 30, 0, tzinfo=timezone.utc)

    # Sets aren't JSON-serializable, so json.dumps raises TypeError.
    bad_payload = {"unserializable": {1, 2, 3}}

    # Must not propagate.
    write_app_setting(db, "yf_business:BAD", bad_payload, fetched_at)

    # No row written on failure.
    row = (
        db.query(AppSetting)
        .filter(AppSetting.key == "yf_business:BAD")
        .first()
    )
    assert row is None
