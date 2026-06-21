"""Integration proof: CSV-imported shares are valid covered-call collateral (#390).

PRD #384 / issue #382 deliver the equity-import pipeline; the covered-call
collateral check already keys purely on ``shares > 0`` and is agnostic to *how*
the shares were acquired (``app.services.covered_call._classify_applicability``).
This file is the **test proof** that the "free" behavior is real: shares brought
in through the Schwab CSV path classify as collateral identically to shares
acquired via option assignment. No production code is changed (AC7c) — these
tests assert against existing behavior.

Resolving #390's open question — *is the collateral check a testable service
function, or router-only?*

    The collateral check is a **directly testable pure service function**:
    ``covered_call._classify_applicability(position, short_call_legs)``. It is
    the single decision point that maps ``(shares, status, has_short_call)`` to
    the ``"covered_call"`` / ``"not_applicable_*"`` applicability buckets, and
    the existing ``test_covered_call_service.py`` unit suite already exercises
    it directly. The router (``GET /api/positions/{id}/covered-call``) merely
    wraps this same function but additionally requires a live Schwab quote +
    option chain to derive its legs. Asserting at the **service level** is
    therefore the right surface: it proves the collateral semantics without
    coupling the proof to a Schwab mock, and it is the exact function a future
    refactor would have to break to regress imported-share collateral.

These tests still go through the **real import pipeline** end to end —
``parse_schwab_csv`` (L1 parser) -> ``execute_mapped_import`` (insert) ->
``recompute_position_state`` (aggregate shares + basis) — so they are genuine
integration tests, not isolated unit calls. The position's share count is read
back from the DB via ``journal.get_position`` and fed to the collateral check,
exactly as the orchestrator does at request time.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position
from app.services import journal
from app.services.covered_call import _classify_applicability
from app.services.positions import recompute_position_state
from app.services.schwab_csv import parse_schwab_csv
from app.services.schwab_import import execute_mapped_import


# --- Fixtures ---------------------------------------------------------------


def _csv(rows: list[str]) -> bytes:
    """Build a Schwab-style CSV from a list of pre-formatted lines.

    Mirrors the helper in ``test_schwab_csv_import.py`` so the synthetic rows
    here parse through the exact production header contract.
    """
    header = "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount"
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


# 100 shares bought directly — the imported-collateral case under test.
STOCK_BUY_100_ROW = "03/01/2026,Buy,AAPL,APPLE INC,100,150.00,1.00,(15001.00)"
# Sell all 100 imported shares back out (AC7b).
STOCK_SELL_100_ROW = "03/10/2026,Sell,AAPL,APPLE INC,100,160.00,1.00,15999.00"
# Sell 60 of the 100 imported shares, leaving 40 (optional partial-sell proof).
STOCK_SELL_60_ROW = "03/10/2026,Sell,AAPL,APPLE INC,60,160.00,1.00,9599.00"


@pytest.fixture()
def db_session():
    """In-memory SQLite session for the equity import + recompute pipeline.

    Standalone (not the ``client`` TestClient fixture) because these tests call
    the import/recompute services directly rather than through HTTP — there is
    no router surface for the collateral check (see module docstring).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


# --- Helpers ----------------------------------------------------------------


def _import_csv(db, rows: list[str]) -> None:
    """Run the real L1 parser -> import -> recompute pipeline for ``rows``.

    ``execute_mapped_import`` already recomputes every touched position before
    it returns, so the position's ``shares`` / ``status`` reflect the ledger by
    the time this helper returns.
    """
    mapped = parse_schwab_csv(_csv(rows))
    execute_mapped_import(db, mapped)


def _only_open_position(db) -> dict:
    """Return the single open position as a ``get_position`` response dict."""
    positions = db.query(Position).filter(Position.status == "open").all()
    assert len(positions) == 1, f"expected exactly one open position, got {len(positions)}"
    resolved = journal.get_position(db, positions[0].id)
    assert resolved is not None
    return resolved


def _any_position(db, ticker: str) -> dict:
    """Return the single position for ``ticker`` (open or closed) as a dict."""
    positions = db.query(Position).filter(Position.ticker == ticker).all()
    assert len(positions) == 1, f"expected exactly one {ticker} position, got {len(positions)}"
    resolved = journal.get_position(db, positions[0].id)
    assert resolved is not None
    return resolved


# A minimal short-call leg in the shape ``_classify_applicability`` consumes —
# the helper only inspects ``any(short_call_legs)`` (and the orchestrator's
# ``type == "call"`` filter), so this matches the leg dicts the existing
# ``test_covered_call_service.py`` unit suite passes.
def _short_call_leg(strike: float = 160.0) -> dict:
    return {"id": "cc-leg-1", "type": "call", "strike": strike, "quantity": 1}


def _make_assigned_position(db, ticker: str = "MSFT") -> dict:
    """Build a 100-share position whose shares came from an option assignment.

    The assignment path is the existing, trusted way shares land on a position:
    a sold cash-secured put is assigned, adding ``qty * 100`` shares at the
    strike. Built directly through the trade ledger + recompute so the share
    count is produced by the same recomputer the import path uses, differing
    only in the acquisition trade_type (``assignment`` vs ``buy_stock``).
    """
    position = Position(
        id="assigned-pos-1",
        ticker=ticker,
        shares=0,
        broker_cost_basis=0.0,
        status="open",
        strategy="csp",
        opened_at="2026-03-01",
    )
    db.add(position)
    db.flush()

    # Sold put that later gets assigned, plus the assignment that delivers 100
    # shares at the $150 strike — mirrors the recomputer's assignment table row.
    journal.create_trade(
        db,
        _trade(position.id, "sell_put", strike=150.0, premium=1.50, opened_at="2026-03-01"),
    )
    journal.create_trade(
        db,
        _trade(position.id, "assignment", strike=150.0, opened_at="2026-03-20"),
    )
    recompute_position_state(db, position.id)
    resolved = journal.get_position(db, position.id)
    assert resolved is not None
    return resolved


def _trade(position_id: str, trade_type: str, **kwargs):
    """Build a ``TradeCreate`` for the assignment-path fixture."""
    from app.models.schemas import TradeCreate

    payload = {
        "position_id": position_id,
        "trade_type": trade_type,
        "quantity": kwargs.get("quantity", 1),
        "expiration": kwargs.get("expiration", "2026-03-20"),
        "fees": kwargs.get("fees", 0.0),
        # ``premium`` is required by TradeCreate; an assignment row carries no
        # premium of its own (the credit lives on the originating sell_put), so
        # it defaults to 0.0 here.
        "premium": kwargs.get("premium", 0.0),
        "opened_at": kwargs.get("opened_at", "2026-03-01"),
    }
    if "strike" in kwargs:
        payload["strike"] = kwargs["strike"]
    return TradeCreate(**payload)


# --- AC7a: imported shares == assigned shares as collateral -----------------


class TestImportedSharesAreValidCollateral:
    """AC7a — CSV-imported shares classify identically to assigned shares."""

    @pytest.mark.integration
    def test_imported_100_shares_classify_as_covered_call(self, db_session):
        # Import 100 shares through the real parser -> import -> recompute path.
        _import_csv(db_session, [STOCK_BUY_100_ROW])

        position = _only_open_position(db_session)
        assert position["shares"] == 100, "import pipeline must aggregate 100 shares"

        # Attach a short call and run the collateral check.
        applicability = _classify_applicability(position, [_short_call_leg()])
        assert applicability == "covered_call"

    @pytest.mark.integration
    def test_imported_shares_match_assigned_shares_classification(self, db_session):
        # Imported-share position.
        _import_csv(db_session, [STOCK_BUY_100_ROW])
        imported = _any_position(db_session, "AAPL")

        # Assigned-share position (the existing trusted collateral path).
        assigned = _make_assigned_position(db_session, ticker="MSFT")

        assert imported["shares"] == 100
        assert assigned["shares"] == 100

        legs = [_short_call_leg()]
        imported_class = _classify_applicability(imported, legs)
        assigned_class = _classify_applicability(assigned, legs)

        # The proof: both classify as valid covered-call collateral, and they
        # classify *identically* — the check cannot tell the two apart.
        assert imported_class == "covered_call"
        assert assigned_class == "covered_call"
        assert imported_class == assigned_class

    @pytest.mark.integration
    def test_imported_shares_without_short_call_are_not_applicable(self, db_session):
        # Sanity: the collateral check is the same gate for imported shares as
        # for any holding — shares alone (no short call) is "no short call",
        # not "no shares". Confirms the share count, not acquisition path, is
        # what flips the bucket.
        _import_csv(db_session, [STOCK_BUY_100_ROW])
        position = _only_open_position(db_session)

        assert _classify_applicability(position, []) == "not_applicable_no_short_call"


# --- AC7b: selling imported shares to zero removes collateral ----------------


class TestSellingImportedSharesRemovesCollateral:
    """AC7b — selling imported shares to zero removes valid CC coverage."""

    @pytest.mark.integration
    def test_selling_all_imported_shares_removes_collateral(self, db_session):
        # Buy 100, then sell all 100 — same import path for both rows.
        _import_csv(db_session, [STOCK_BUY_100_ROW])
        before = _any_position(db_session, "AAPL")
        assert before["shares"] == 100
        assert _classify_applicability(before, [_short_call_leg()]) == "covered_call"

        _import_csv(db_session, [STOCK_SELL_100_ROW])
        after = _any_position(db_session, "AAPL")

        # A fully-sold equity position reaches shares == 0 with no open legs and
        # closes naturally via the recomputer's close-at-zero path (positions.py
        # docstring). The closed-status short-circuit therefore wins ordering in
        # ``_classify_applicability``, so the outcome is "not_applicable_closed"
        # rather than "not_applicable_no_shares". Either is a non-covered
        # outcome (no valid CC coverage); we assert the actual one the pipeline
        # produces and document which here.
        assert after["shares"] == 0
        assert after["status"] == "closed"
        assert (
            _classify_applicability(after, [_short_call_leg()])
            == "not_applicable_closed"
        )

    @pytest.mark.integration
    def test_zero_shares_open_position_is_no_shares(self, db_session):
        # Direct confirmation of the other non-covered branch: a position that
        # holds zero shares but is still *open* classifies as
        # "not_applicable_no_shares". This isolates the share-count gate from
        # the closed short-circuit — proving selling-to-zero removes collateral
        # regardless of which terminal state the recomputer lands on.
        position = {"shares": 0, "status": "open"}
        assert (
            _classify_applicability(position, [_short_call_leg()])
            == "not_applicable_no_shares"
        )


# --- Optional: partial sell still leaves valid collateral -------------------


class TestPartialSellKeepsCollateral:
    """Strengthens the proof — a partial sell still covers a 1-contract CC."""

    @pytest.mark.integration
    def test_partial_sell_to_40_shares_still_classifies_as_covered_call(self, db_session):
        # Buy 100, sell 60 -> 40 shares remain. A single (40-share-equivalent
        # would need <1 contract; a 1-contract CC sized to the remaining lot is
        # still considered to have collateral by the shares > 0 gate).
        _import_csv(db_session, [STOCK_BUY_100_ROW])
        _import_csv(db_session, [STOCK_SELL_60_ROW])

        position = _any_position(db_session, "AAPL")
        assert position["shares"] == 40
        assert position["status"] == "open"
        assert (
            _classify_applicability(position, [_short_call_leg()]) == "covered_call"
        )
