"""QA test-data seeding + deterministic stub-pricing fixtures (issue #349).

QA (``qa.regression.shawnjsandy.com``) has no positions and no Schwab feed, so
the v1.7 covered-call decision surfaces (#318 assignment-risk depth, #319 BTC
panel, #320 per-share basis) cannot be validated there before promoting to prod.
This module seeds seven synthetic position archetypes — plus the deterministic
stub-pricing rows that light up the live-feed-dependent surfaces — so every v1.7
acceptance criterion renders its intended state on QA.

**Prod safety (hard block, no override):** :func:`assert_seed_allowed` raises
:class:`SeedGuardError` when ``settings.app_env == "production"`` *before any DB
write*. Prod compose sets ``APP_ENV=production``; the seeder can never write
synthetic data to the prod database.

**Authoritative full reset (ADR #359 D2):** ``seed-qa`` on QA performs a
**full reset** — it wipes *all* rows from ``positions`` / ``trades`` /
``quote_stubs`` / ``option_mark_stubs`` (plus ``trade_entry_compliance``, a FK
child of ``trades``) and then inserts the seven archetypes. It deliberately
leaves ``app_settings`` / ``sessions`` / ``watchlist`` untouched so QA stays
signed-in and configured. Every run therefore yields exactly the archetypes:
no manual prod-delete is ever needed again, and reseeding yields seven
positions — not fourteen. This supersedes #349's additive "delete-only-tagged"
teardown, which assumed QA would never carry prod data.

A rolling ``create_backup`` is taken before the destructive wipe as cheap undo
insurance. Positions still carry a ``"__seed__:<key>"`` sentinel prefix in
``notes`` so the archetypes remain identifiable after seeding.

**Recomputer bypass (deliberate):** the archetypes pin derived state
(``shares`` / ``broker_cost_basis`` / ``strategy`` / ``status``) directly on the
ORM row because the seed validates the *display* features, not the recomputer.
Calling :func:`recompute_position_state` would overwrite the pinned state. The
one read-time-derived value, ``adjusted_cost_basis``, is computed by
``journal.py`` from the seeded trades — so archetype 7 carries real
premium-bearing trades to make ``adjusted_cost_basis`` differ from broker basis.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.database import (
    OptionMarkStub,
    Position,
    QuoteStub,
    Trade,
    TradeEntryCompliance,
)
from app.services.backup import create_backup

logger = logging.getLogger(__name__)

# Sentinel prefix written to a seeded position's ``notes`` column so the
# archetypes remain identifiable after seeding. Frozen contract — the tests
# reference this literal.
SEED_TAG_PREFIX: str = "__seed__:"

# The expected number of archetypes a healthy seed run inserts. The deploy
# auto-seed gate (ADR #359 D3) fails the deploy if the post-seed count differs.
EXPECTED_ARCHETYPE_COUNT: int = 7


class SeedGuardError(Exception):
    """Raised when a seed run is attempted against the production environment.

    The guard is a hard block with no override — there is no flag that lets
    ``seed-qa`` write synthetic data to the prod database.
    """


@dataclass(frozen=True)
class StubMark:
    """A single deterministic option mark to seed for an archetype's leg."""

    strike: float
    expiration: str  # YYYY-MM-DD
    option_type: str  # "call" | "put"
    mid: float
    delta: float | None = None


@dataclass(frozen=True)
class SeedTrade:
    """A synthetic trade ledger entry for an archetype position."""

    trade_type: str
    strike: float
    expiration: str  # YYYY-MM-DD
    premium: float  # per-share, positive for credits
    quantity: int = 1
    fees: float = 0.0
    closed_at: str | None = None
    close_reason: str | None = None


@dataclass(frozen=True)
class Archetype:
    """A frozen synthetic-position fixture (issue #349 contract-freeze source).

    The ``ARCHETYPES`` list below is the single source of truth referenced by
    both the seeder and the tests. Derived state (``shares`` /
    ``broker_cost_basis`` / ``strategy`` / ``status``) is pinned directly on the
    ORM row; the recomputer is deliberately not run (see module docstring).
    """

    key: str
    ticker: str
    shares: int
    broker_cost_basis: float
    strategy: str
    intended_state: str
    trades: list[SeedTrade] = field(default_factory=list)
    quote_price: float | None = None
    marks: list[StubMark] = field(default_factory=list)


@dataclass
class SeedResult:
    """Outcome of a seed run.

    ``positions_seeded`` counts positions inserted (0 on a dry run).
    ``quotes_seeded`` / ``marks_seeded`` count stub rows inserted.
    ``failed_archetypes`` lists archetype keys whose insert raised — a non-empty
    list drives the CLI's non-zero exit. ``dry_run`` echoes the run mode.
    """

    positions_seeded: int = 0
    quotes_seeded: int = 0
    marks_seeded: int = 0
    failed_archetypes: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        """True when no archetype failed to insert."""
        return not self.failed_archetypes


def _iso_date_in(days: int, *, now: datetime) -> str:
    """Return the YYYY-MM-DD date ``days`` from ``now`` (UTC).

    Expirations are computed from ``datetime.now(timezone.utc)`` rather than
    pinned ISO literals so a DTE-relative archetype keeps its intended
    near/far-dated state regardless of when the seed runs (Wave 3 date-drift
    lesson — a pinned literal silently drifts out of its DTE window over time).
    """
    return (now + timedelta(days=days)).date().isoformat()


def build_archetypes(now: datetime | None = None) -> list[Archetype]:
    """Construct the seven synthetic archetypes with DTE-relative expirations.

    ``now`` is injectable for deterministic tests; production callers omit it
    and get ``datetime.now(timezone.utc)``. Returns a fresh list each call (the
    expirations depend on ``now``), but the *shape* — keys, tickers, strategy,
    intended state — is frozen.

    Archetype matrix (issue #349 plan §3):

    1. Deep-ITM short call, >14 DTE, δ≈0.90 → #318 **High** (depth axis).
    2. NTM short call, ≤14 DTE, ITM, δ≈0.55 → #318 **Watch** (timing axis).
    3. OTM short call, long DTE, δ≈0.25 → #318 **Low**.
    4. Covered call, normal premium, live stub mark → #319 BTC panel populated,
       ``pricing_source="stub"``.
    5. Cash-secured put, 0 shares → #319 covered-call-only N/A gate + #320
       0-share basis em-dash. No stub marks (CSP is not a covered call).
    6. Covered call, no live option mark → #319 degraded ``"—"`` sentinel,
       ``pricing_source="unavailable"`` (quote seeded, mark omitted).
    7. Multi-share equity, premium-bearing trades → #320 adjusted/sh ≠ broker/sh.
    """
    now = now or datetime.now(timezone.utc)
    far = _iso_date_in(30, now=now)  # > 14 DTE
    # 10 DTE: inside the ≤14 "watch" timing band but above the ≤7 "high" floor,
    # so the timing axis yields Watch (the depth axis stays Low at δ≈0.55).
    near = _iso_date_in(10, now=now)
    past = _iso_date_in(-30, now=now)  # closed-leg expiration in the past

    return [
        # 1 — Deep-ITM short call, >14 DTE, δ≈0.90 → High (depth axis).
        Archetype(
            key="deep_itm_call",
            ticker="SEEDA",
            shares=100,
            broker_cost_basis=8000.0,
            strategy="cc",
            intended_state="#318 assignment risk = High (deep ITM)",
            trades=[
                SeedTrade("sell_call", strike=80.0, expiration=far, premium=12.0),
            ],
            quote_price=110.0,  # price ≫ strike → deep ITM
            marks=[
                StubMark(80.0, far, "call", mid=31.5, delta=0.90),
            ],
        ),
        # 2 — NTM short call, ≤14 DTE, ITM, δ≈0.55 → Watch (timing axis).
        Archetype(
            key="ntm_call",
            ticker="SEEDB",
            shares=100,
            broker_cost_basis=5000.0,
            strategy="cc",
            intended_state="#318 assignment risk = Watch (near-dated ITM)",
            trades=[
                SeedTrade("sell_call", strike=50.0, expiration=near, premium=2.5),
            ],
            quote_price=51.0,  # slightly ITM
            marks=[
                StubMark(50.0, near, "call", mid=1.6, delta=0.55),
            ],
        ),
        # 3 — OTM short call, long DTE, δ≈0.25 → Low.
        Archetype(
            key="otm_call",
            ticker="SEEDC",
            shares=100,
            broker_cost_basis=6000.0,
            strategy="cc",
            intended_state="#318 assignment risk = Low (OTM)",
            trades=[
                SeedTrade("sell_call", strike=70.0, expiration=far, premium=1.8),
            ],
            quote_price=62.0,  # price < strike → OTM
            marks=[
                StubMark(70.0, far, "call", mid=1.2, delta=0.25),
            ],
        ),
        # 4 — Covered call, normal premium, live stub mark → BTC panel populated.
        Archetype(
            key="btc_populated_cc",
            ticker="SEEDD",
            shares=100,
            broker_cost_basis=4500.0,
            strategy="cc",
            intended_state="#319 BTC panel populated, pricing_source=stub",
            trades=[
                SeedTrade("sell_call", strike=48.0, expiration=far, premium=2.2),
            ],
            quote_price=46.0,  # OTM, mid present → full BTC math
            marks=[
                StubMark(48.0, far, "call", mid=1.1, delta=0.30),
            ],
        ),
        # 5 — Cash-secured put, 0 shares → CC-only N/A gate + 0-share basis dash.
        Archetype(
            key="csp_zero_shares",
            ticker="SEEDE",
            shares=0,
            broker_cost_basis=0.0,
            strategy="csp",
            intended_state="#319 CC-only N/A + #320 0-share basis em-dash",
            trades=[
                SeedTrade("sell_put", strike=40.0, expiration=far, premium=1.5),
            ],
            quote_price=42.0,  # put is OTM; no marks (CSP ≠ covered call)
            marks=[],
        ),
        # 6 — Covered call, NO live option mark → degraded "—" sentinel.
        Archetype(
            key="cc_no_mark",
            ticker="SEEDF",
            shares=100,
            broker_cost_basis=5500.0,
            strategy="cc",
            intended_state="#319 degraded '—' sentinel, pricing_source=unavailable",
            trades=[
                SeedTrade("sell_call", strike=55.0, expiration=far, premium=2.0),
            ],
            quote_price=54.0,  # quote present, mark omitted → greek-null degrade
            marks=[],
        ),
        # 7 — Multi-share equity, premium-bearing trades → adjusted/sh ≠ broker/sh.
        Archetype(
            key="equity_adjusted_basis",
            ticker="SEEDG",
            shares=100,
            broker_cost_basis=7000.0,
            strategy="wheel",
            intended_state="#320 adjusted/sh ≠ broker/sh (premium-reduced basis)",
            trades=[
                # Closed premium-bearing legs reduce adjusted basis below broker.
                SeedTrade(
                    "sell_call",
                    strike=75.0,
                    expiration=past,
                    premium=3.0,
                    closed_at=past + "T00:00:00+00:00",
                    close_reason="full_expiration",
                ),
                SeedTrade(
                    "sell_call",
                    strike=72.0,
                    expiration=past,
                    premium=2.5,
                    closed_at=past + "T00:00:00+00:00",
                    close_reason="full_expiration",
                ),
            ],
            quote_price=78.0,
            marks=[],
        ),
    ]


def assert_seed_allowed() -> None:
    """Hard-block seeding on production (issue #349).

    Raises :class:`SeedGuardError` when ``settings.app_env == "production"``.
    Called first by :func:`seed_qa`, before any DB read or write, so synthetic
    data can never reach the prod database. There is no override.
    """
    if settings.app_env == "production":
        logger.warning(
            "seed_qa.refused",
            extra={
                "event": "seed_qa.refused",
                "outcome": "failed",
                "app_env": settings.app_env,
            },
        )
        raise SeedGuardError(
            "QA seeding is blocked on the production environment (APP_ENV=production)."
        )


def _full_reset(db: DBSession) -> None:
    """Wipe ALL position/trade/stub rows so the seed is authoritative (ADR #359 D2).

    Bulk-deletes every row from ``trade_entry_compliance`` (a FK child of
    ``trades``), ``trades``, ``positions``, ``quote_stubs``, and
    ``option_mark_stubs`` — *not* only sentinel-tagged rows. This leaves
    ``app_settings`` / ``sessions`` / ``watchlist`` untouched so QA stays
    signed-in and configured (resolved blast radius, ADR #359 Q2).

    The deletes are ordered child-before-parent and use bulk ``query().delete()``
    rather than ORM-cascade deletes because (a) the project does not enable
    ``PRAGMA foreign_keys=ON`` so SQL-level cascade never fires, and (b) a bulk
    delete is the same pattern :func:`journal.clear_all_journal_data` uses for a
    large parent set.

    **SAFETY:** callers MUST invoke :func:`assert_seed_allowed` first — this
    function performs no guard of its own and is catastrophic on production.
    """
    db.query(TradeEntryCompliance).delete(synchronize_session=False)
    db.query(Trade).delete(synchronize_session=False)
    db.query(Position).delete(synchronize_session=False)
    db.query(QuoteStub).delete(synchronize_session=False)
    db.query(OptionMarkStub).delete(synchronize_session=False)
    db.commit()


def _insert_archetype(db: DBSession, archetype: Archetype, *, now: datetime) -> int:
    """Insert one archetype's position, trades, and stub rows. Returns stub count.

    Pins derived state directly on the ORM row (no recomputer). Tags the
    position ``notes`` with the seed sentinel. Commits so a later archetype's
    failure does not roll back an already-inserted archetype. Returns the number
    of stub rows (quote + marks) written for this archetype.
    """
    opened_at = now.replace(microsecond=0).isoformat()
    position = Position(
        id=str(uuid.uuid4()),
        ticker=archetype.ticker,
        shares=archetype.shares,
        broker_cost_basis=archetype.broker_cost_basis,
        status="open",
        strategy=archetype.strategy,
        opened_at=opened_at,
        notes=f"{SEED_TAG_PREFIX}{archetype.key}",
    )
    db.add(position)
    db.flush()  # assign position.id for the trade FK

    for spec in archetype.trades:
        db.add(
            Trade(
                id=str(uuid.uuid4()),
                position_id=position.id,
                trade_type=spec.trade_type,
                strike=spec.strike,
                expiration=spec.expiration,
                premium=spec.premium,
                fees=spec.fees,
                quantity=spec.quantity,
                opened_at=opened_at,
                closed_at=spec.closed_at,
                close_reason=spec.close_reason,
            )
        )

    stub_count = 0
    if archetype.quote_price is not None:
        db.add(QuoteStub(ticker=archetype.ticker, last_price=archetype.quote_price))
        stub_count += 1
    for mark in archetype.marks:
        db.add(
            OptionMarkStub(
                id=str(uuid.uuid4()),
                ticker=archetype.ticker,
                strike=mark.strike,
                expiration=mark.expiration,
                option_type=mark.option_type,
                mid=mark.mid,
                delta=mark.delta,
            )
        )
        stub_count += 1

    db.commit()
    return stub_count


def seed_qa(db: DBSession, *, dry_run: bool = False) -> SeedResult:
    """Seed QA with the seven synthetic archetypes + stub-pricing rows.

    Guards against production first (raising :class:`SeedGuardError` before any
    read or write), then performs an **authoritative full reset** (ADR #359 D2):
    a rolling ``create_backup`` is taken, ALL position/trade/stub rows are wiped
    (``app_settings`` / ``sessions`` / ``watchlist`` preserved), and the seven
    archetypes are inserted. A per-archetype insert failure is collected (its key
    added to ``SeedResult.failed_archetypes``) and the run continues, so one bad
    archetype does not abort the rest; the CLI exits non-zero when any failed.

    ``dry_run=True`` performs no writes and no backup — it builds the archetype
    list (to surface construction errors) and returns counts of zero.
    """
    assert_seed_allowed()
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    archetypes = build_archetypes(now)

    if dry_run:
        logger.info(
            "seed_qa.dry_run",
            extra={
                "event": "seed_qa.dry_run",
                "outcome": "success",
                "app_env": settings.app_env,
            },
        )
        return SeedResult(dry_run=True)

    # Cheap undo insurance before the destructive wipe (ADR #359 Q3). A backup
    # failure must not abort the seed — log it and proceed; the reset is the
    # load-bearing operation, the backup is best-effort.
    try:
        backup_name = create_backup()
    except Exception as exc:
        logger.warning(
            "seed_qa.backup_failed",
            extra={
                "event": "seed_qa.backup_failed",
                "outcome": "degraded",
                "error_class": type(exc).__name__,
            },
        )
        backup_name = ""

    _full_reset(db)
    logger.info(
        "seed_qa.reset",
        extra={
            "event": "seed_qa.reset",
            "outcome": "success",
            "duration_ms": round((time.monotonic() - start) * 1000, 2),
            "app_env": settings.app_env,
            "backup": backup_name or None,
        },
    )

    result = SeedResult()
    for archetype in archetypes:
        try:
            stub_count = _insert_archetype(db, archetype, now=now)
        except Exception as exc:
            db.rollback()
            logger.exception(
                "seed_qa.archetype_failed",
                extra={
                    "event": "seed_qa.archetype_failed",
                    "outcome": "failed",
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                    "error_class": type(exc).__name__,
                    "archetype": archetype.key,
                },
            )
            result.failed_archetypes.append(archetype.key)
            continue
        result.positions_seeded += 1
        # The quote (if any) is the first stub row; the rest are marks.
        if archetype.quote_price is not None:
            result.quotes_seeded += 1
            result.marks_seeded += stub_count - 1
        else:
            result.marks_seeded += stub_count

    logger.info(
        "seed_qa.complete",
        extra={
            "event": "seed_qa.complete",
            "outcome": "success" if result.ok else "degraded",
            "duration_ms": round((time.monotonic() - start) * 1000, 2),
            "app_env": settings.app_env,
            "positions_seeded": result.positions_seeded,
            "quotes_seeded": result.quotes_seeded,
            "marks_seeded": result.marks_seeded,
            "failed_count": len(result.failed_archetypes),
        },
    )
    return result


__all__ = [
    "EXPECTED_ARCHETYPE_COUNT",
    "SEED_TAG_PREFIX",
    "Archetype",
    "SeedGuardError",
    "SeedResult",
    "SeedTrade",
    "StubMark",
    "assert_seed_allowed",
    "build_archetypes",
    "seed_qa",
]
