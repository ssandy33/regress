"""Migration + integrity tests for the ``position_notes`` table (issue #280).

The project has no Alembic — ``init_db()`` simply calls
``Base.metadata.create_all(bind=engine)`` and SQLAlchemy is idempotent.
These tests assert the table appears on a fresh DB, that the FK + UNIQUE
constraints hold, and that the "down" path (manual ``DROP TABLE``)
cleanly removes the table without disturbing siblings. This stands in
for the missing Alembic ``downgrade`` step the implementation plan
explicitly documents as a manual operation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, PositionNote


def _make_engine():
    """Build an isolated in-memory SQLite engine with FK enforcement on."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite has FK support off by default — enable it so the FK column
    # on position_notes actually rejects orphans.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _seed_position(session, position_id: str | None = None) -> str:
    """Insert a minimal Position and return its id."""
    pid = position_id or str(uuid.uuid4())
    session.add(
        Position(
            id=pid,
            ticker="AAPL",
            shares=100,
            broker_cost_basis=15000.0,
            status="open",
            strategy="csp",
            opened_at="2026-01-01T00:00:00Z",
        )
    )
    session.commit()
    return pid


# --- Migration up: table appears via create_all ---


@pytest.mark.unit
def test_create_all_creates_position_notes_table():
    """``Base.metadata.create_all`` materializes the new table."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    assert "position_notes" in inspector.get_table_names()


@pytest.mark.unit
def test_position_notes_columns_match_plan():
    """Frozen column set per plan §3.2 / §4.3."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    cols = {c["name"]: c for c in inspector.get_columns("position_notes")}
    assert set(cols.keys()) == {
        "id",
        "position_id",
        "body",
        "version",
        "updated_at",
        "updated_by",
    }
    # ``body`` is the column name the API and frontend round-trip on —
    # rename-here would break the contract.
    assert "body" in cols


@pytest.mark.unit
def test_position_notes_position_id_indexed():
    """``position_id`` is indexed (frequent lookup column)."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("position_notes")
    indexed_cols = {col for idx in indexes for col in idx["column_names"]}
    assert "position_id" in indexed_cols


# --- Migration down: explicit DROP TABLE cleans up ---


@pytest.mark.unit
def test_drop_table_removes_position_notes_without_touching_positions():
    """The documented manual rollback path removes only the new table."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    assert "position_notes" in inspector.get_table_names()
    assert "positions" in inspector.get_table_names()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE position_notes"))

    # Re-introspect with a fresh inspector — SQLAlchemy caches tables.
    inspector = inspect(engine)
    assert "position_notes" not in inspector.get_table_names()
    assert "positions" in inspector.get_table_names()


@pytest.mark.unit
def test_create_all_is_idempotent():
    """Calling ``create_all`` twice on an existing DB is a no-op."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    # Second call must not raise even though the table already exists.
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    assert "position_notes" in inspector.get_table_names()


# --- Constraint enforcement ---


@pytest.mark.unit
def test_unique_constraint_on_position_id():
    """A single position can hold only one note row."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        pid = _seed_position(session)

        session.add(
            PositionNote(
                id=str(uuid.uuid4()),
                position_id=pid,
                body="first",
                version=1,
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.commit()

        session.add(
            PositionNote(
                id=str(uuid.uuid4()),
                position_id=pid,
                body="second",
                version=1,
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


@pytest.mark.unit
def test_fk_rejects_orphan_position_id():
    """A note pointing at a non-existent position is rejected."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.add(
            PositionNote(
                id=str(uuid.uuid4()),
                position_id="does-not-exist",
                body="orphan",
                version=1,
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


@pytest.mark.unit
def test_body_roundtrips_unchanged():
    """``body`` is the column name and the text survives a round-trip."""
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        pid = _seed_position(session)
        original = "Long thesis with newlines\n\nand unicode — café —."
        session.add(
            PositionNote(
                id=str(uuid.uuid4()),
                position_id=pid,
                body=original,
                version=1,
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.commit()

        fetched = (
            session.query(PositionNote)
            .filter(PositionNote.position_id == pid)
            .one()
        )
        assert fetched.body == original
    finally:
        session.close()
