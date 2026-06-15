"""Integration tests for the QA stub-pricing render paths (issue #349).

Seeds the synthetic archetypes, switches ``pricing_mode`` to ``"stub"``, and
drives the real dashboard + BTC-detail services to confirm the v1.7 surfaces
render their intended states off the deterministic stub feed:

- #318 assignment-risk depth → High / Watch / Low for archetypes 1 / 2 / 3.
- #319 BTC panel populated with ``pricing_source="stub"`` (archetype 4) and the
  degraded ``"unavailable"`` path (archetype 6).
- #320 per-share basis is feed-independent (covered in the seed integration
  suite); the CSP N/A gate is asserted here via the BTC analysis shape.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.services import seed_qa as seed_mod
from app.services.btc_detail import build_btc_detail
from app.services.dashboard import build_dashboard_payload


@pytest.fixture()
def stub_db():
    """In-memory SQLite seeded with the archetypes under pricing_mode=stub.

    Patches ``settings.app_env`` / ``settings.pricing_mode`` across every module
    that reads them on the seed + render paths, so the whole flow runs in stub
    mode with no live Schwab dependency.
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
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    with patch("app.services.seed_qa.settings") as seed_settings, patch(
        "app.services.dashboard.settings"
    ) as dash_settings, patch(
        "app.services.market_client.settings"
    ) as mc_settings, patch(
        "app.services.btc_detail.settings"
    ) as btc_settings:
        for s in (seed_settings, dash_settings, mc_settings, btc_settings):
            s.app_env = "qa"
            s.pricing_mode = "stub"
        seed_mod.seed_qa(session)
        yield session

    session.close()


def _leg_risk_by_ticker(payload) -> dict[str, str]:
    """Map each open leg's ticker → its assignment_risk bucket."""
    return {leg["ticker"]: leg["assignment_risk"] for leg in payload["open_legs"]}


def _position_id(db, ticker) -> str:
    from app.models.database import Position

    return db.query(Position).filter(Position.ticker == ticker).first().id


def _leg_id_for_position(payload, position_id) -> str:
    leg = next(
        lg for lg in payload["open_legs"] if lg["position_id"] == position_id
    )
    return leg["id"]


@pytest.mark.integration
def test_dashboard_assignment_risk_high_watch_low_with_stub(stub_db):
    """AC #318: archetypes 1/2/3 render High/Watch/Low off the stub feed."""
    payload = build_dashboard_payload(stub_db)
    risk = _leg_risk_by_ticker(payload)
    assert risk["SEEDA"] == "high"  # deep-ITM, δ≈0.90
    assert risk["SEEDB"] == "watch"  # near-dated ITM
    assert risk["SEEDC"] == "low"  # OTM


@pytest.mark.integration
def test_btc_panel_populated_with_stub(stub_db):
    """AC #319 live-mark path: archetype 4 → populated panel, pricing_source=stub."""
    payload = build_dashboard_payload(stub_db)
    pos_id = _position_id(stub_db, "SEEDD")
    leg_id = _leg_id_for_position(payload, pos_id)

    detail = build_btc_detail(stub_db, pos_id, leg_id)
    assert detail is not None
    assert detail["analysis"]["available"] is True
    assert detail["analysis"]["scenarios"]  # non-empty scenario grid
    assert detail["economics"]["pricing_source"] == "stub"
    assert detail["economics"]["current_option_mid"] is not None


@pytest.mark.integration
def test_btc_degraded_when_mark_missing(stub_db):
    """AC #319 degraded path: archetype 6 → '—' sentinel, pricing_source=unavailable."""
    payload = build_dashboard_payload(stub_db)
    pos_id = _position_id(stub_db, "SEEDF")
    leg_id = _leg_id_for_position(payload, pos_id)

    detail = build_btc_detail(stub_db, pos_id, leg_id)
    assert detail is not None
    # Quote present but no option mark → economics degrade to "unavailable".
    assert detail["economics"]["pricing_source"] == "unavailable"
    assert detail["economics"]["current_option_mid"] is None
    assert detail["economics"]["cost_to_close"] is None


@pytest.mark.integration
def test_csp_btc_is_not_applicable(stub_db):
    """AC #319 CC-only gate: archetype 5 (CSP) → analysis not available."""
    payload = build_dashboard_payload(stub_db)
    pos_id = _position_id(stub_db, "SEEDE")
    leg_id = _leg_id_for_position(payload, pos_id)

    detail = build_btc_detail(stub_db, pos_id, leg_id)
    assert detail is not None
    # The BTC decision math gates puts out (CC-scoped) → not available.
    assert detail["analysis"]["available"] is False


@pytest.mark.integration
def test_stub_client_snapshots_data_and_retains_no_session(stub_db):
    """Regression (#349): the stub client must snapshot its data at
    construction and NOT touch the DB session afterwards.

    The dashboard calls ``get_quote`` / ``get_option_chain`` from
    ``ThreadPoolExecutor`` workers; a SQLAlchemy ``Session`` and its SQLite
    connection used cross-thread raise ``sqlite3.InterfaceError: bad parameter
    or other API misuse``, which silently degraded every leg's risk to "low"
    (the original PR #351 CI failure). Locking the structural invariant — no
    retained session, plain in-memory snapshot dicts — catches any
    reintroduction of per-call DB access.
    """
    from app.services.market_client import StubSchwabClient

    client = StubSchwabClient(stub_db)

    # No retained session handle; data is held as plain dicts.
    assert not hasattr(client, "_db")
    assert isinstance(client._quotes, dict) and client._quotes
    assert isinstance(client._marks, dict) and client._marks

    # Serves from the snapshot even after the source session is closed.
    stub_db.close()
    assert client.get_quote("SEEDA")["lastPrice"] is not None
    assert client.get_option_chain("SEEDA")["callExpDateMap"]
