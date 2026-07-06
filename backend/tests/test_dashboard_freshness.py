"""Unit tests for the honest quote-freshness signal (issue #417, PRD #415 R5).

Covers:
- ``_market_reference_now`` / ``_most_recent_session_close`` — the market-hours
  reference the freshness age is measured against (``now`` during RTH, else the
  most recent session close), so weekends/after-hours don't false-positive
  (Risk #2 — the 2026-07-04 evidence was itself a market-closed day).
- ``_compute_quote_freshness`` — per-symbol age / stale flag / fetched-at ISO
  from a ``QuoteView.quote_time_ms``, including the unassessable (no timestamp)
  degrade path.
- ``_build_quote_freshness_signal`` — the aggregate displayed-quote pill signal
  (``displayed_total`` / ``displayed_stale`` / ``stalest_symbol`` /
  ``stalest_age_seconds``) driven by the OLDEST displayed quote.
- ``_build_position_rows`` — stamps the freshness fields on each row.

All timestamps are derived from an explicit reference instant (no pinned ISO
literals, per CLAUDE.md) so the assertions stay valid as wall-clock advances.
All are pure-function tests (no DB session, no TestClient) → ``@pytest.mark.unit``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.dashboard import (
    QUOTE_FRESH_BUDGET_SECONDS,
    QuoteView,
    _build_position_rows,
    _build_quote_freshness_signal,
    _compute_quote_freshness,
    _market_reference_now,
    _most_recent_session_close,
)
from app.services.dashboard_legs import MARKET_TZ
from app.services.market_client import _iso_to_epoch_millis
from app.services.seed_qa import build_archetypes


def _et(year, month, day, hour, minute=0) -> datetime:
    """An Eastern-tz aware datetime (the market calendar the reference uses)."""
    return datetime(year, month, day, hour, minute, tzinfo=MARKET_TZ)


def _quote_time_ms(dt: datetime) -> int:
    """Epoch millis for ``dt`` — the shape Schwab's ``quoteTime`` (and QuoteView) uses."""
    return int(dt.timestamp() * 1000)


# --- market reference (Risk #2) --------------------------------------------


@pytest.mark.unit
def test_market_reference_is_now_during_rth():
    """During regular trading hours the reference is ``now`` — quotes must keep
    updating, so age accrues in real time."""
    # 2026-07-08 is a Wednesday; 14:00 ET is inside 09:30–16:00.
    now = _et(2026, 7, 8, 14, 0)
    assert _market_reference_now(now) == now


@pytest.mark.unit
def test_market_reference_is_last_close_on_weekend():
    """On a weekend the reference is the most recent session close, not ``now`` —
    a quote captured near Friday's close is not "stale" all weekend."""
    # 2026-07-11 is a Saturday; most recent close is Friday 2026-07-10 16:00 ET.
    now = _et(2026, 7, 11, 12, 0)
    expected = _et(2026, 7, 10, 16, 0).astimezone(timezone.utc)
    assert _market_reference_now(now) == expected


@pytest.mark.unit
def test_market_reference_after_close_uses_today_close():
    """After 16:00 on a weekday the reference is today's close."""
    # Wednesday 2026-07-08 20:00 ET → today's 16:00 close.
    now = _et(2026, 7, 8, 20, 0)
    expected = _et(2026, 7, 8, 16, 0).astimezone(timezone.utc)
    assert _market_reference_now(now) == expected


@pytest.mark.unit
def test_market_reference_pre_open_uses_prior_session_close():
    """Before 09:30 on a weekday the reference is the previous session close."""
    # Wednesday 2026-07-08 08:00 ET (pre-open) → Tuesday 2026-07-07 16:00 close.
    now = _et(2026, 7, 8, 8, 0)
    expected = _et(2026, 7, 7, 16, 0).astimezone(timezone.utc)
    assert _market_reference_now(now) == expected


@pytest.mark.unit
def test_most_recent_session_close_skips_weekend():
    """Monday pre-open rewinds over the weekend to Friday's close."""
    # Monday 2026-07-13 08:00 ET → Friday 2026-07-10 16:00 close.
    monday = _et(2026, 7, 13, 8, 0)
    expected = _et(2026, 7, 10, 16, 0).astimezone(timezone.utc)
    assert _most_recent_session_close(monday) == expected


# --- per-symbol freshness ---------------------------------------------------


@pytest.mark.unit
def test_compute_quote_freshness_fresh_during_rth():
    """A 5-minute-old quote during RTH is fresh (age under the 15m budget)."""
    reference = _et(2026, 7, 8, 14, 0).astimezone(timezone.utc)
    quote_dt = reference - timedelta(minutes=5)
    view = QuoteView(last=12.5, quote_time_ms=_quote_time_ms(quote_dt))
    age, stale, fetched_at = _compute_quote_freshness(view, reference)
    assert age == pytest.approx(300, abs=1)
    assert stale is False
    assert fetched_at == quote_dt.astimezone(timezone.utc).isoformat()


@pytest.mark.unit
def test_compute_quote_freshness_stale_past_budget():
    """A quote older than the intraday budget is flagged stale."""
    reference = _et(2026, 7, 8, 14, 0).astimezone(timezone.utc)
    quote_dt = reference - timedelta(seconds=QUOTE_FRESH_BUDGET_SECONDS + 60)
    view = QuoteView(last=12.5, quote_time_ms=_quote_time_ms(quote_dt))
    age, stale, _ = _compute_quote_freshness(view, reference)
    assert age > QUOTE_FRESH_BUDGET_SECONDS
    assert stale is True


@pytest.mark.unit
def test_stale_flag_respects_market_hours_budget():
    """A quote captured 2 minutes before Friday's close is NOT stale on Saturday
    (measured against the last session close), even though its wall-clock age is
    ~a day. This is the Risk #2 / #417 core guarantee."""
    saturday = _et(2026, 7, 11, 12, 0)
    reference = _market_reference_now(saturday)  # Friday 16:00 close
    quote_dt = _et(2026, 7, 10, 15, 58).astimezone(timezone.utc)  # 2m before close
    view = QuoteView(last=12.5, quote_time_ms=_quote_time_ms(quote_dt))
    age, stale, _ = _compute_quote_freshness(view, reference)
    assert age == pytest.approx(120, abs=1)
    assert stale is False


@pytest.mark.unit
def test_stale_flag_fires_for_quote_that_died_mid_session():
    """A quote that stopped updating 3h before Friday's close IS stale on Saturday
    — market-hours suppression does not mask a genuinely dead feed."""
    saturday = _et(2026, 7, 11, 12, 0)
    reference = _market_reference_now(saturday)  # Friday 16:00 close
    quote_dt = _et(2026, 7, 10, 13, 0).astimezone(timezone.utc)  # 3h before close
    view = QuoteView(last=12.5, quote_time_ms=_quote_time_ms(quote_dt))
    age, stale, _ = _compute_quote_freshness(view, reference)
    assert age == pytest.approx(3 * 3600, abs=2)
    assert stale is True


@pytest.mark.unit
def test_compute_quote_freshness_unassessable_when_no_timestamp():
    """No ``quoteTime`` → null age + not-stale (never a false stale flag)."""
    reference = datetime.now(timezone.utc)
    age, stale, fetched_at = _compute_quote_freshness(QuoteView(last=12.5), reference)
    assert age is None
    assert stale is False
    assert fetched_at is None


@pytest.mark.unit
def test_compute_quote_freshness_none_view():
    """A missing view degrades to unassessable, never raises."""
    assert _compute_quote_freshness(None, datetime.now(timezone.utc)) == (
        None,
        False,
        None,
    )


# --- aggregate pill signal --------------------------------------------------


def _row(ticker, age, stale):
    return {"ticker": ticker, "quote_age_seconds": age, "quote_stale": stale}


@pytest.mark.unit
def test_no_stale_flag_when_all_fresh():
    rows = [_row("NOK", 60, False), _row("BB", 120, False)]
    signal = _build_quote_freshness_signal(rows)
    assert signal["displayed_total"] == 2
    assert signal["displayed_stale"] == 0


@pytest.mark.unit
def test_displayed_stale_count():
    rows = [
        _row("NOK", 60, False),
        _row("BB", 4000, True),
        _row("SOFI", 5000, True),
    ]
    signal = _build_quote_freshness_signal(rows)
    assert signal["displayed_total"] == 3
    assert signal["displayed_stale"] == 2


@pytest.mark.unit
def test_freshness_driven_by_stalest_quote():
    """The reported staleness reflects the OLDEST displayed quote, not an
    aggregate/average — this is the #417 bug fix."""
    rows = [
        _row("NOK", 200, False),
        _row("BB", 10800, True),  # 3h — the stalest
        _row("SOFI", 900, False),
    ]
    signal = _build_quote_freshness_signal(rows)
    assert signal["stalest_symbol"] == "BB"
    assert signal["stalest_age_seconds"] == 10800


@pytest.mark.unit
def test_stalest_symbol_and_age_reported():
    rows = [_row("F", 30, False), _row("PLTR", 45, False)]
    signal = _build_quote_freshness_signal(rows)
    # Even when nothing is stale, the oldest quote is named for the hover.
    assert signal["stalest_symbol"] == "PLTR"
    assert signal["stalest_age_seconds"] == 45


@pytest.mark.unit
def test_stalest_ties_broken_alphabetically():
    rows = [_row("ZM", 500, False), _row("AA", 500, False)]
    signal = _build_quote_freshness_signal(rows)
    assert signal["stalest_symbol"] == "AA"


@pytest.mark.unit
def test_unassessable_rows_excluded_from_displayed_total():
    """Rows whose quote carried no timestamp are not counted as displayed quotes."""
    rows = [_row("NOK", None, False), _row("BB", 4000, True)]
    signal = _build_quote_freshness_signal(rows)
    assert signal["displayed_total"] == 1
    assert signal["displayed_stale"] == 1
    assert signal["stalest_symbol"] == "BB"


@pytest.mark.unit
def test_empty_rows_yield_null_stalest():
    signal = _build_quote_freshness_signal([])
    assert signal["displayed_total"] == 0
    assert signal["displayed_stale"] == 0
    assert signal["stalest_symbol"] is None
    assert signal["stalest_age_seconds"] is None


# --- row stamping -----------------------------------------------------------


@pytest.mark.unit
def test_build_position_rows_stamps_freshness_fields():
    """``_build_position_rows`` stamps age/stale/fetched_at from the rich quote
    against a market-hours reference derived from the injected ``now``."""
    now = _et(2026, 7, 8, 14, 0).astimezone(timezone.utc)  # Wednesday RTH
    stale_dt = now - timedelta(hours=3)
    positions = [
        {
            "id": "p-1",
            "ticker": "NOK",
            "shares": 100,
            "adjusted_cost_basis": 1200.0,
            "strategy": "holding",
            "broker_cost_basis": 1200.0,
        }
    ]
    rich = {"NOK": QuoteView(last=12.5, quote_time_ms=_quote_time_ms(stale_dt))}
    rows = _build_position_rows(
        positions, {"NOK": 12.5}, [], rich_quotes=rich, now=now
    )
    row = rows[0]
    assert row["quote_age_seconds"] == pytest.approx(3 * 3600, abs=2)
    assert row["quote_stale"] is True
    assert row["quote_fetched_at"] == stale_dt.astimezone(timezone.utc).isoformat()


# --- QA seed archetype (#417 QA-demoable data) ------------------------------


@pytest.mark.unit
def test_qa_stale_archetype_flags_stale_during_market_hours():
    """The QA seed's stale archetype (SEEDH, ~3h-old quote) renders the amber
    stale flag when viewed during regular trading hours — the normal QA demo
    window. Ties the seed_qa fixture to the #417 rendered state."""
    # Seed at a Wednesday 14:00 ET instant (RTH); reference == now, so a 3h-old
    # quote is 3h stale.
    seed_now = _et(2026, 7, 8, 14, 0).astimezone(timezone.utc)
    archetypes = build_archetypes(now=seed_now)
    stale_arch = next(a for a in archetypes if a.ticker == "SEEDH")
    assert stale_arch.quote_time is not None

    view = QuoteView(
        last=stale_arch.quote_price,
        quote_time_ms=_iso_to_epoch_millis(stale_arch.quote_time),
    )
    age, stale, _ = _compute_quote_freshness(view, _market_reference_now(seed_now))
    assert stale is True
    assert age > QUOTE_FRESH_BUDGET_SECONDS


@pytest.mark.unit
def test_qa_fresh_archetype_is_not_stale():
    """The QA seed's fresh archetype (SEEDA, ~2m-old quote) carries no stale flag."""
    seed_now = _et(2026, 7, 8, 14, 0).astimezone(timezone.utc)
    archetypes = build_archetypes(now=seed_now)
    fresh_arch = next(a for a in archetypes if a.ticker == "SEEDA")
    view = QuoteView(
        last=fresh_arch.quote_price,
        quote_time_ms=_iso_to_epoch_millis(fresh_arch.quote_time),
    )
    _, stale, _ = _compute_quote_freshness(view, _market_reference_now(seed_now))
    assert stale is False


@pytest.mark.unit
def test_build_position_rows_freshness_null_without_rich_quote():
    """A row with no rich quote gets null age + not-stale (legacy callers)."""
    positions = [
        {
            "id": "p-1",
            "ticker": "NOK",
            "shares": 100,
            "adjusted_cost_basis": 1200.0,
            "strategy": "holding",
            "broker_cost_basis": 1200.0,
        }
    ]
    rows = _build_position_rows(positions, {"NOK": 12.5}, [])
    assert rows[0]["quote_age_seconds"] is None
    assert rows[0]["quote_stale"] is False
    assert rows[0]["quote_fetched_at"] is None
