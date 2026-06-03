"""Persistence integration test for the watchlist (issue #321 / PRD #213 R7).

Proves the watchlist survives an application restart. The in-memory ``client``
fixture cannot model this (a ``:memory:`` DB dies with its connection pool), so
this test uses an on-disk SQLite file in a tmp dir: it writes through one
engine/session ("session A"), disposes it, then opens a brand-new
engine/session ("session B") bound to the same file and reads the ticker back —
the moral equivalent of stopping and restarting the process.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import Base
from app.services.watchlist import add_ticker, list_watchlist


@pytest.mark.integration
def test_watchlist_survives_session_recreation(tmp_path):
    """P1 — a ticker added in one session is readable from a fresh session.

    Each session gets its own ``Engine`` (its own connection pool) bound to the
    same on-disk SQLite file, so the read genuinely crosses a process-restart
    boundary rather than reusing an open connection.
    """
    db_path = tmp_path / "watchlist_persistence.db"
    db_url = f"sqlite:///{db_path}"

    # --- Session A: create schema + add a ticker, then tear the engine down. ---
    engine_a = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine_a)
    session_a = sessionmaker(bind=engine_a)()
    try:
        add_ticker(session_a, "aapl")
    finally:
        session_a.close()
    engine_a.dispose()

    # --- Session B: a brand-new engine on the same file simulates a restart. ---
    engine_b = create_engine(db_url, connect_args={"check_same_thread": False})
    session_b = sessionmaker(bind=engine_b)()
    try:
        assert list_watchlist(session_b) == ["AAPL"]
    finally:
        session_b.close()
    engine_b.dispose()
