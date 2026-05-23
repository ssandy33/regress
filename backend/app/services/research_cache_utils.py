"""Shared AppSetting cache helpers for the research services (issue #284).

Extracts the previously duplicated ``_read_app_setting`` /
``_write_app_setting`` functions from :mod:`app.services.research_business`
and :mod:`app.services.research_financials` into a single module so the
durable-cache pattern has exactly one source of truth.

The on-disk format is unchanged: ``app_settings.value`` stores
``"{iso8601_timestamp}|{json_payload}"`` so the timestamp is recoverable
without a separate column. Both callers honor a 24h TTL on the timestamp
half; this module is TTL-agnostic and returns the timestamp untouched.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def read_app_setting(
    db: Session, key: str
) -> Optional[tuple[dict, datetime]]:
    """Return ``(payload, fetched_at)`` from ``app_settings`` or ``None``.

    Returns ``None`` for any of:

    - missing row,
    - malformed value (empty timestamp half, empty JSON half, non-dict
      JSON, or a timestamp that does not parse via
      :func:`datetime.fromisoformat`),
    - DB-layer error (``SQLAlchemyError``).

    Errors are logged at DEBUG, never propagated — the caller treats a
    ``None`` as a cache miss and falls through to its upstream fetch.
    """
    try:
        from app.models.database import AppSetting

        entry = db.query(AppSetting).filter(AppSetting.key == key).first()
        if entry is None:
            return None
        ts_part, _, json_part = entry.value.partition("|")
        if not ts_part or not json_part:
            return None
        fetched_at = datetime.fromisoformat(ts_part)
        payload = json.loads(json_part)
        if not isinstance(payload, dict):
            return None
        return payload, fetched_at
    except (SQLAlchemyError, ValueError) as exc:
        logger.debug(
            "Failed to read app_setting",
            extra={"app_setting_key": key, "error": str(exc)},
        )
        return None


def write_app_setting(
    db: Session, key: str, payload: dict, fetched_at: datetime
) -> None:
    """Upsert ``payload`` into ``app_settings`` under ``key``.

    Serialized format is ``"{fetched_at.isoformat()}|{json.dumps(payload)}"``.
    On any DB-layer failure the function logs at DEBUG and best-effort
    rollback; the caller never sees an exception.
    """
    try:
        from app.models.database import AppSetting

        value = f"{fetched_at.isoformat()}|{json.dumps(payload)}"
        entry = db.query(AppSetting).filter(AppSetting.key == key).first()
        if entry is None:
            db.add(AppSetting(key=key, value=value))
        else:
            entry.value = value
        db.commit()
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        # ``TypeError`` covers non-JSON-serializable payloads from
        # ``json.dumps`` (e.g. sets, custom objects) so the helper still
        # honors its "never propagate" contract (CodeRabbit PR #289).
        logger.debug(
            "Failed to write app_setting",
            extra={"app_setting_key": key, "error": str(exc)},
        )
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
