"""Thesis note service for the research page (issue #280, Section F).

Two operations, one row per position:

* :func:`get_thesis` — returns the current thesis or the empty-state shape
  (``thesis=None``, ``version=0``) when no row exists.
* :func:`put_thesis` — upserts the thesis body, bumps the ``version`` and
  ``updated_at`` columns on every successful write. Pre-validates the
  body length (server-side defence in depth — Pydantic already enforces
  the cap on the request model).

Position-existence is checked against the ``positions`` table; if the
position is unknown both endpoints raise :class:`PositionNotFoundError`
which the router translates to ``404``. Body overflows raise
:class:`ThesisTooLongError` which the router translates to ``422``.
Neither error class leaks raw exception text — both carry a sanitized
message per CLAUDE.md.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.database import Position, PositionNote
from app.models.schemas import THESIS_MAX_BODY_LENGTH, ThesisResponse

logger = logging.getLogger(__name__)


class PositionNotFoundError(Exception):
    """Raised when a position id does not resolve to a known row."""


class ThesisTooLongError(Exception):
    """Raised when a thesis body exceeds :data:`THESIS_MAX_BODY_LENGTH`."""


def _utc_now_iso() -> str:
    """Return the current UTC instant in ISO-8601 with a ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _position_exists(db: Session, position_id: str) -> bool:
    """Lightweight existence check on the ``positions`` table."""
    return (
        db.query(Position.id)
        .filter(Position.id == position_id)
        .first()
        is not None
    )


def _empty_response() -> ThesisResponse:
    """Build the empty-state response (no row yet) per spec §F."""
    return ThesisResponse(thesis=None, updated_at=None, version=0)


def _row_to_response(note: PositionNote) -> ThesisResponse:
    """Serialize a persisted ``PositionNote`` to the public response shape."""
    return ThesisResponse(
        thesis=note.body,
        updated_at=note.updated_at,
        version=note.version,
    )


def get_thesis(db: Session, position_id: str) -> ThesisResponse:
    """Return the thesis row for ``position_id`` or the empty-state shape.

    Raises :class:`PositionNotFoundError` when the position itself does
    not exist — the router maps that to ``404``. When the position
    exists but no thesis row is present, returns the empty-state
    response (``thesis=None``, ``version=0``).
    """
    if not _position_exists(db, position_id):
        raise PositionNotFoundError(position_id)

    note = (
        db.query(PositionNote)
        .filter(PositionNote.position_id == position_id)
        .first()
    )
    if note is None:
        return _empty_response()
    return _row_to_response(note)


def put_thesis(db: Session, position_id: str, body: str) -> ThesisResponse:
    """Upsert the thesis for ``position_id`` and return the new row.

    On insert: ``version`` starts at 1. On update: ``version`` is
    incremented and ``updated_at`` refreshed. The body may be empty —
    empty strings are explicitly allowed and still bump the version
    (the plan does not forbid clearing the note).

    Raises:
        :class:`PositionNotFoundError`: position id does not exist.
        :class:`ThesisTooLongError`: body length exceeds the cap.
    """
    if len(body) > THESIS_MAX_BODY_LENGTH:
        raise ThesisTooLongError(
            f"Thesis exceeds {THESIS_MAX_BODY_LENGTH} character limit"
        )

    if not _position_exists(db, position_id):
        raise PositionNotFoundError(position_id)

    note = (
        db.query(PositionNote)
        .filter(PositionNote.position_id == position_id)
        .first()
    )
    now_iso = _utc_now_iso()

    if note is None:
        note = PositionNote(
            id=str(uuid.uuid4()),
            position_id=position_id,
            body=body,
            version=1,
            updated_at=now_iso,
            updated_by=None,
        )
        db.add(note)
    else:
        note.body = body
        note.version = note.version + 1
        note.updated_at = now_iso

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to upsert thesis",
            extra={"position_id": position_id},
        )
        raise

    db.refresh(note)
    logger.info(
        "Upserted thesis",
        extra={"position_id": position_id, "version": note.version},
    )
    return _row_to_response(note)
