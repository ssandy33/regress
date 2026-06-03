"""Watchlist service — the approved-underlying universe (issue #321).

The watchlist is the operational form of the wheel-strategy "would I
voluntarily own this?" gate (PRD #213). This module is the **data-access +
business-logic layer** behind ``/api/watchlist``; the scanner integration
(PRD #213 R5) and the management UI (R6 consumer) are sibling V1.6 issues that
read through :func:`list_watchlist`.

Storage is a dedicated ``watchlist`` table keyed on ``ticker`` (PRD #213 Q1 —
see :class:`app.models.database.WatchlistTicker`). The primary key makes both
mutations idempotent for free:

- **add** — present-check then insert; adding an existing ticker is a no-op
  (PRD #213 R2).
- **remove** — ``DELETE`` by primary key; removing a missing ticker affects
  zero rows and is a no-op (PRD #213 R3).

Every ticker is uppercase-normalized via :func:`normalize_ticker` before it
touches the table, so the case-insensitive duplicate (``aapl`` after ``AAPL``)
collapses onto the same primary-key row.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from app.models.database import WatchlistTicker


def normalize_ticker(raw: str) -> str:
    """Normalize a raw ticker to its canonical stored form.

    Strips surrounding whitespace and uppercases. This is the single
    normalization rule shared by the ``POST`` request body and the ``DELETE``
    path parameter so ``aapl`` and ``AAPL`` always resolve to the same row.

    The caller is responsible for rejecting empty input — the API boundary
    (``WatchlistAddRequest`` / the route) does this before reaching the
    persistence layer.
    """
    return raw.strip().upper()


def list_watchlist(db: DBSession) -> list[str]:
    """Return the current watchlist as a list of uppercase tickers.

    Ordered oldest-added first (``added_at`` then ``ticker``) for a stable,
    deterministic response. Returns an empty list when no names are approved.
    """
    rows = (
        db.query(WatchlistTicker)
        .order_by(WatchlistTicker.added_at, WatchlistTicker.ticker)
        .all()
    )
    return [row.ticker for row in rows]


def add_ticker(db: DBSession, raw_ticker: str) -> list[str]:
    """Add a ticker to the watchlist (idempotent) and return the updated list.

    Normalizes ``raw_ticker`` to uppercase. Adding a ticker that already
    exists is a no-op — no duplicate row, no error (PRD #213 R2). Returns the
    full, current watchlist.
    """
    ticker = normalize_ticker(raw_ticker)
    existing = db.get(WatchlistTicker, ticker)
    if existing is None:
        db.add(
            WatchlistTicker(
                ticker=ticker,
                added_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        db.commit()
    return list_watchlist(db)


def remove_ticker(db: DBSession, raw_ticker: str) -> list[str]:
    """Remove a ticker from the watchlist (idempotent) and return the list.

    Normalizes ``raw_ticker`` to uppercase. Removing a ticker that is not on
    the watchlist is a no-op — no error (PRD #213 R3). Returns the full,
    current watchlist.
    """
    ticker = normalize_ticker(raw_ticker)
    existing = db.get(WatchlistTicker, ticker)
    if existing is not None:
        db.delete(existing)
        db.commit()
    return list_watchlist(db)
