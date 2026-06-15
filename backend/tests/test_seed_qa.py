"""Unit tests for the QA seed mechanism (issue #349).

Pure-Python: no DB session, no TestClient, no network. Covers the prod guard,
the archetype-construction contract, and the stub client's Schwab-shaped output.
DB-touching behavior (idempotency, dry-run writes, render paths) lives in the
integration suites.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.dashboard_legs import build_option_leg_index, compute_dte
from app.services.market_client import StubSchwabClient, get_market_client
from app.services.schwab_client import SchwabClient, SchwabClientError
from app.services.seed_qa import (
    SEED_TAG_PREFIX,
    SeedGuardError,
    assert_seed_allowed,
    build_archetypes,
)

_FIXED_NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


# --- Prod guard (Component 1) ---


@pytest.mark.unit
def test_assert_seed_allowed_blocks_production():
    """AC: prod guard tested — APP_ENV=production raises SeedGuardError."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = "production"
        with pytest.raises(SeedGuardError):
            assert_seed_allowed()


@pytest.mark.unit
@pytest.mark.parametrize("env", ["qa", "development", "test"])
def test_assert_seed_allowed_permits_non_production(env):
    """Non-prod environments proceed without raising."""
    with patch("app.services.seed_qa.settings") as mock_settings:
        mock_settings.app_env = env
        assert assert_seed_allowed() is None


# --- Archetype contract (Components 2-3) ---


@pytest.mark.unit
def test_build_archetypes_yields_seven_with_unique_keys():
    """The frozen archetype list is exactly seven with distinct keys."""
    archetypes = build_archetypes(_FIXED_NOW)
    assert len(archetypes) == 7
    keys = [a.key for a in archetypes]
    assert len(set(keys)) == 7


@pytest.mark.unit
def test_archetype_expirations_are_dte_relative_not_pinned():
    """Expirations are computed from ``now`` so they don't drift out of window."""
    later = _FIXED_NOW + timedelta(days=90)
    first = {a.key: a for a in build_archetypes(_FIXED_NOW)}
    second = {a.key: a for a in build_archetypes(later)}
    # The far-dated leg shifts by 90 days when ``now`` shifts by 90 days.
    exp_first = first["deep_itm_call"].trades[0].expiration
    exp_second = second["deep_itm_call"].trades[0].expiration
    assert exp_first != exp_second


@pytest.mark.unit
def test_archetype_deep_itm_call_derived_state():
    """Archetype 1: deep-ITM short call, >14 DTE, δ≈0.90 (High depth axis)."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["deep_itm_call"]
    assert arch.strategy == "cc"
    assert arch.shares == 100
    leg = arch.trades[0]
    assert leg.trade_type == "sell_call"
    # price ≫ strike → deep ITM.
    assert arch.quote_price > leg.strike
    assert compute_dte(leg.expiration, today=_FIXED_NOW.date()) > 14
    assert arch.marks[0].delta == 0.90


@pytest.mark.unit
def test_archetype_ntm_call_derived_state():
    """Archetype 2: near-the-money short call, ≤14 DTE, ITM (Watch timing axis)."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["ntm_call"]
    assert arch.strategy == "cc"
    leg = arch.trades[0]
    assert arch.quote_price > leg.strike  # ITM
    assert compute_dte(leg.expiration, today=_FIXED_NOW.date()) <= 14
    assert 0.5 <= arch.marks[0].delta < 0.6


@pytest.mark.unit
def test_archetype_otm_call_derived_state():
    """Archetype 3: OTM short call, long DTE, low delta (Low)."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["otm_call"]
    leg = arch.trades[0]
    assert arch.quote_price < leg.strike  # OTM
    assert arch.marks[0].delta < 0.6


@pytest.mark.unit
def test_archetype_btc_populated_has_mark():
    """Archetype 4: covered call with a live stub mark (BTC panel populated)."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["btc_populated_cc"]
    assert arch.strategy == "cc"
    assert arch.quote_price is not None
    assert len(arch.marks) == 1
    assert arch.marks[0].mid > 0


@pytest.mark.unit
def test_archetype_csp_zero_shares_derived_state():
    """Archetype 5: cash-secured put, 0 shares, 0 basis, no marks."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["csp_zero_shares"]
    assert arch.strategy == "csp"
    assert arch.shares == 0
    assert arch.broker_cost_basis == 0.0
    assert arch.trades[0].trade_type == "sell_put"
    assert arch.marks == []  # CSP is not a covered call → no stub marks


@pytest.mark.unit
def test_archetype_cc_no_mark_omits_marks():
    """Archetype 6: covered call with a quote but no option mark (degraded)."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["cc_no_mark"]
    assert arch.strategy == "cc"
    assert arch.quote_price is not None  # quote present
    assert arch.marks == []  # mark omitted → "—" degrade path


@pytest.mark.unit
def test_archetype_equity_adjusted_basis_has_premium_trades():
    """Archetype 7: equity with premium-bearing trades so adjusted ≠ broker."""
    arch = {a.key: a for a in build_archetypes(_FIXED_NOW)}["equity_adjusted_basis"]
    assert arch.shares == 100
    assert arch.broker_cost_basis > 0
    assert len(arch.trades) >= 2
    assert all(t.premium > 0 for t in arch.trades)


@pytest.mark.unit
def test_seed_tag_prefix_is_frozen():
    """The teardown sentinel prefix is the frozen contract literal."""
    assert SEED_TAG_PREFIX == "__seed__:"


# --- Stub pricing (Component 4) ---


class _FakeQuery:
    """Minimal stand-in for a SQLAlchemy Query bound to a fixed result set."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeMark:
    def __init__(self, ticker, strike, expiration, option_type, mid, delta):
        self.ticker = ticker
        self.strike = strike
        self.expiration = expiration
        self.option_type = option_type
        self.mid = mid
        self.delta = delta


class _FakeQuote:
    def __init__(self, ticker, last_price):
        self.ticker = ticker
        self.last_price = last_price


class _FakeDB:
    """A fake DB session whose ``query`` returns canned QuoteStub/OptionMarkStub rows."""

    def __init__(self, quotes=None, marks=None):
        self._quotes = quotes or []
        self._marks = marks or []

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "QuoteStub":
            return _FakeQuery(self._quotes)
        if name == "OptionMarkStub":
            return _FakeQuery(self._marks)
        return _FakeQuery([])


@pytest.mark.unit
def test_stub_client_returns_schwab_shaped_quote_and_chain():
    """StubSchwabClient output parses through build_option_leg_index unchanged."""
    db = _FakeDB(
        quotes=[_FakeQuote("SEEDA", 110.0)],
        marks=[_FakeMark("SEEDA", 80.0, "2026-07-15", "call", 31.5, 0.90)],
    )
    client = StubSchwabClient(db)

    quote = client.get_quote("SEEDA")
    assert quote["lastPrice"] == 110.0

    chain = client.get_option_chain("SEEDA")
    assert "callExpDateMap" in chain and "putExpDateMap" in chain

    index = build_option_leg_index({"SEEDA": chain}, spots_by_ticker={"SEEDA": 110.0})
    entry = index[("SEEDA", "call", 80.0, "2026-07-15")]
    assert entry["mid"] == 31.5
    assert entry["delta"] == 0.90


@pytest.mark.unit
def test_stub_client_raises_on_missing_quote():
    """A ticker with no stub quote raises SchwabClientError (live-client contract)."""
    client = StubSchwabClient(_FakeDB())
    with pytest.raises(SchwabClientError):
        client.get_quote("NOPE")


@pytest.mark.unit
def test_stub_client_returns_empty_chain_when_no_marks():
    """A ticker with no stub marks returns a valid empty chain (degrade path).

    The "no live option mark" archetype must degrade to ``current_mid=None``,
    not 500 the page — so the stub returns empty maps rather than raising.
    """
    client = StubSchwabClient(_FakeDB())
    chain = client.get_option_chain("NOPE")
    assert chain["callExpDateMap"] == {}
    assert chain["putExpDateMap"] == {}


@pytest.mark.unit
def test_get_market_client_factory_selects_by_mode():
    """live → SchwabClient; stub → StubSchwabClient (non-prod)."""
    db = _FakeDB()
    with patch("app.services.market_client.settings") as mock_settings:
        mock_settings.app_env = "qa"
        mock_settings.pricing_mode = "live"
        assert isinstance(get_market_client(db), SchwabClient)
        mock_settings.pricing_mode = "stub"
        assert isinstance(get_market_client(db), StubSchwabClient)


@pytest.mark.unit
def test_get_market_client_refuses_stub_on_production():
    """Defense-in-depth: pricing_mode=stub on production falls back to live.

    The configuration invariant (prod never sets PRICING_MODE) is the first
    guard; this proves a stray prod override still cannot serve synthetic data.
    """
    db = _FakeDB()
    with patch("app.services.market_client.settings") as mock_settings:
        mock_settings.app_env = "production"
        mock_settings.pricing_mode = "stub"
        assert isinstance(get_market_client(db), SchwabClient)
