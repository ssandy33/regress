"""Integration tests for the QA seed mechanism (issue #349, hardened by #360).

Full ORM stack against in-memory SQLite. Covers the idempotent authoritative
full reset (ADR #359 D2 — wipes all positions/trades/stub rows then inserts the
7 archetypes), the preserved-table blast radius (app_settings/sessions/watchlist
survive), dry-run no-write semantics, the per-archetype derived state as
persisted, and the CLI's non-zero exit on archetype failure.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import (
    AppSetting,
    Base,
    OptionMarkStub,
    Position,
    QuoteStub,
    Session,
    Trade,
    WatchlistTicker,
)
from app.services import journal
from app.services.seed_qa import (
    EXPECTED_ARCHETYPE_COUNT,
    SEED_TAG_PREFIX,
    SeedGuardError,
    seed_qa,
)


@pytest.fixture()
def db_session():
    """In-memory SQLite session with the full schema created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _no_op_backup():
    """Stub the rolling pre-reset backup so tests never touch a real DB file.

    ``seed_qa`` calls ``create_backup`` before the destructive wipe. Against the
    in-memory session there is no file to copy, but patching keeps the test from
    accidentally backing up a stray ``./regression_tool.db`` in the cwd.
    """
    with patch("app.services.seed_qa.create_backup", return_value="") as mock:
        yield mock


def _seed_count(db) -> int:
    """Count sentinel-tagged seeded positions."""
    return (
        db.query(Position)
        .filter(Position.notes.like(f"{SEED_TAG_PREFIX}%"))
        .count()
    )


@pytest.mark.integration
@pytest.mark.ac("349-AC9")
def test_seed_inserts_all_seven_archetypes(db_session):
    """AC: all archetypes present — seven seeded positions after a seed run."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        result = seed_qa(db_session)
    assert result.positions_seeded == 7
    assert result.ok
    assert _seed_count(db_session) == 7
    # Stub rows seeded for the feed-dependent archetypes.
    assert db_session.query(QuoteStub).count() >= 1
    assert db_session.query(OptionMarkStub).count() >= 1


@pytest.mark.integration
@pytest.mark.ac("349-AC8")
def test_seed_is_idempotent(db_session):
    """AC: repeatable reseed — running twice yields 7 positions, not 14."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        seed_qa(db_session)
        quotes_after_first = db_session.query(QuoteStub).count()
        seed_qa(db_session)
    assert _seed_count(db_session) == 7
    # Stub rows are also reset, not doubled.
    assert db_session.query(QuoteStub).count() == quotes_after_first


@pytest.mark.integration
@pytest.mark.ac("349-AC8")
def test_seed_full_reset_wipes_untagged_rows(db_session):
    """#360-AC2: authoritative full reset — pre-existing (e.g. prod-shaped) rows
    are WIPED, not preserved. Supersedes #349's non-destructive teardown.

    A manually-added position with its own trade is present before the seed; after
    the reset the DB holds exactly the 7 archetypes and nothing else.
    """
    manual = Position(
        id=str(uuid.uuid4()),
        ticker="MANUAL",
        shares=100,
        broker_cost_basis=1000.0,
        status="open",
        strategy="wheel",
        opened_at="2026-01-01T00:00:00+00:00",
        notes="hand-entered, not seeded",
    )
    db_session.add(manual)
    db_session.flush()
    db_session.add(
        Trade(
            id=str(uuid.uuid4()),
            position_id=manual.id,
            trade_type="sell_call",
            strike=10.0,
            expiration="2026-12-31",
            premium=1.0,
            fees=0.0,
            quantity=1,
            opened_at="2026-01-01T00:00:00+00:00",
        )
    )
    db_session.commit()

    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        seed_qa(db_session)

    # The untagged row is gone — full reset, not additive.
    survivor = (
        db_session.query(Position).filter(Position.ticker == "MANUAL").first()
    )
    assert survivor is None
    # Exactly the archetypes remain; no other positions linger.
    assert _seed_count(db_session) == EXPECTED_ARCHETYPE_COUNT
    assert db_session.query(Position).count() == EXPECTED_ARCHETYPE_COUNT


@pytest.mark.integration
def test_seed_full_reset_preserves_auth_config_watchlist(db_session):
    """#360-AC2 (blast radius, ADR #359 Q2): the reset wipes only position/trade/
    stub tables — app_settings, sessions, and watchlist survive so QA stays
    signed-in and configured.
    """
    db_session.add(AppSetting(key="rules_config", value="{}"))
    db_session.add(
        Session(
            id=str(uuid.uuid4()),
            name="my-session",
            config="{}",
            results=None,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    db_session.add(
        WatchlistTicker(ticker="AAPL", added_at="2026-01-01T00:00:00+00:00")
    )
    db_session.commit()

    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        seed_qa(db_session)

    assert db_session.query(AppSetting).filter_by(key="rules_config").count() == 1
    assert db_session.query(Session).count() == 1
    assert db_session.query(WatchlistTicker).filter_by(ticker="AAPL").count() == 1
    # And the archetypes seeded alongside the preserved state.
    assert _seed_count(db_session) == EXPECTED_ARCHETYPE_COUNT


@pytest.mark.integration
@pytest.mark.ac("349-AC10")
def test_seed_dry_run_writes_nothing(db_session):
    """AC: dry-run — dry_run=True writes no positions or stub rows."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        result = seed_qa(db_session, dry_run=True)
    assert result.dry_run is True
    assert result.positions_seeded == 0
    assert db_session.query(Position).count() == 0
    assert db_session.query(QuoteStub).count() == 0
    assert db_session.query(OptionMarkStub).count() == 0


@pytest.mark.integration
@pytest.mark.ac("349-AC9")
def test_seed_nonzero_exit_on_archetype_failure(db_session):
    """AC: exits non-zero on failure — a failed insert surfaces the key.

    Force ``_insert_archetype`` to raise for one archetype; the run continues,
    collects the failed key, and ``SeedResult.ok`` is False (the CLI maps that
    to a non-zero exit).
    """
    from app.services import seed_qa as seed_mod

    real_insert = seed_mod._insert_archetype

    def _flaky_insert(db, archetype, *, now):
        if archetype.key == "otm_call":
            raise RuntimeError("forced insert failure")
        return real_insert(db, archetype, now=now)

    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        with patch.object(seed_mod, "_insert_archetype", _flaky_insert):
            result = seed_qa(db_session)

    assert not result.ok
    assert "otm_call" in result.failed_archetypes
    # The other six still seeded.
    assert result.positions_seeded == 6


@pytest.mark.integration
@pytest.mark.ac("349-AC5")
def test_csp_archetype_persists_zero_share_basis(db_session):
    """Archetype 5: CSP persists with 0 shares → per-share basis is None (#320)."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        seed_qa(db_session)
    csp = (
        db_session.query(Position).filter(Position.ticker == "SEEDE").first()
    )
    assert csp.shares == 0
    response = journal.get_position(db_session, csp.id)
    assert response["broker_cost_basis_per_share"] is None
    assert response["adjusted_cost_basis_per_share"] is None


@pytest.mark.integration
@pytest.mark.ac("349-AC7")
def test_equity_archetype_adjusted_basis_differs_from_broker(db_session):
    """Archetype 7: premium-bearing trades make adjusted/sh ≠ broker/sh (#320)."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "qa"
        seed_qa(db_session)
    equity = (
        db_session.query(Position).filter(Position.ticker == "SEEDG").first()
    )
    response = journal.get_position(db_session, equity.id)
    assert response["broker_cost_basis_per_share"] is not None
    assert response["adjusted_cost_basis_per_share"] is not None
    assert (
        response["adjusted_cost_basis_per_share"]
        != response["broker_cost_basis_per_share"]
    )


@pytest.mark.integration
@pytest.mark.ac("349-AC11", "349-AC12")
def test_full_reset_never_runs_on_production(db_session):
    """#360-AC3 (SAFETY): the destructive full reset is hard-blocked under
    APP_ENV=production — ``seed_qa`` raises SeedGuardError and writes nothing.

    Pre-existing rows are present; after the refused run they are untouched (the
    guard fires before ``_full_reset`` and before any insert), proving the
    catastrophic wipe is unreachable on prod.
    """
    survivor = Position(
        id=str(uuid.uuid4()),
        ticker="REALPROD",
        shares=100,
        broker_cost_basis=1000.0,
        status="open",
        strategy="wheel",
        opened_at="2026-01-01T00:00:00+00:00",
        notes="real prod-shaped row",
    )
    db_session.add(survivor)
    db_session.commit()

    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "production"
        with patch(
            "app.services.seed_qa._full_reset"
        ) as mock_reset, patch(
            "app.services.seed_qa._insert_archetype"
        ) as mock_insert:
            with pytest.raises(SeedGuardError):
                seed_qa(db_session)

    # Neither the wipe nor any insert ran.
    mock_reset.assert_not_called()
    mock_insert.assert_not_called()
    # The pre-existing row is exactly as it was — nothing wiped, nothing seeded.
    assert db_session.query(Position).count() == 1
    assert (
        db_session.query(Position).filter_by(ticker="REALPROD").count() == 1
    )
    assert _seed_count(db_session) == 0


@pytest.mark.integration
@pytest.mark.ac("349-AC8")
def test_seed_takes_backup_before_reset(db_session):
    """#360-AC2 (ADR #359 Q3): a rolling create_backup runs before the wipe.

    The autouse stub already patches create_backup; here we assert it is invoked
    exactly once on a QA seed (the cheap-undo insurance).
    """
    with patch("app.services.seed_qa.settings") as mock_settings, patch(
        "app.services.seed_qa.create_backup", return_value="backup.db"
    ) as mock_backup:
        mock_settings.app_env = "qa"
        seed_qa(db_session)
    mock_backup.assert_called_once()


@pytest.mark.integration
@pytest.mark.ac("349-AC10")
def test_seed_dry_run_skips_backup_and_reset(db_session):
    """#360-AC2: dry_run takes no backup and performs no wipe."""
    existing = Position(
        id=str(uuid.uuid4()),
        ticker="KEEPME",
        shares=10,
        broker_cost_basis=100.0,
        status="open",
        strategy="wheel",
        opened_at="2026-01-01T00:00:00+00:00",
        notes="present before dry run",
    )
    db_session.add(existing)
    db_session.commit()

    with patch("app.services.seed_qa.settings") as mock_settings, patch(
        "app.services.seed_qa.create_backup"
    ) as mock_backup, patch(
        "app.services.seed_qa._full_reset"
    ) as mock_reset:
        mock_settings.app_env = "qa"
        result = seed_qa(db_session, dry_run=True)

    assert result.dry_run is True
    mock_backup.assert_not_called()
    mock_reset.assert_not_called()
    # The pre-existing row survives a dry run untouched.
    assert db_session.query(Position).filter_by(ticker="KEEPME").count() == 1
