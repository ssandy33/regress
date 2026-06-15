from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class CacheEntry(Base):
    __tablename__ = "cache"

    asset_key = Column(String, primary_key=True)  # e.g. "schwab:AAPL", "fred:DGS10"
    data = Column(Text, nullable=False)  # JSON-serialized DataFrame
    fetched_at = Column(String, nullable=False)  # ISO datetime
    source_frequency = Column(String, nullable=False)  # daily / monthly / quarterly
    source_name = Column(String, nullable=False)  # schwab / fred / zillow


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)  # UUID4
    name = Column(String, nullable=False)
    config = Column(Text, nullable=False)  # JSON: regression type, parameters
    results = Column(Text, nullable=True)  # JSON: regression output
    created_at = Column(String, nullable=False)  # ISO datetime
    updated_at = Column(String, nullable=False)  # ISO datetime


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


class Position(Base):
    __tablename__ = "positions"

    id = Column(String, primary_key=True)  # UUID4
    ticker = Column(String, nullable=False)
    shares = Column(Integer, nullable=False, default=100)
    # Cost basis matching IRS/Schwab convention: ``strike × shares − net
    # premium of the assigned put`` (net premium = ``gross_premium × 100 ×
    # contracts − fees_prorated``). Falls back to raw ``strike × shares`` when
    # no originating short put can be matched to an assignment (orphan
    # imports); the un-netted case is logged at WARNING. Recomputed on every
    # ledger replay by ``recompute_position_state`` — never written directly.
    broker_cost_basis = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="open")  # "open" | "closed"
    strategy = Column(String, nullable=False)  # "csp" | "cc" | "wheel"
    opened_at = Column(String, nullable=False)  # ISO datetime
    closed_at = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    trades = relationship(
        "Trade",
        back_populates="position",
        order_by="Trade.opened_at",
        cascade="all, delete-orphan",
    )


class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True)  # UUID4
    position_id = Column(String, ForeignKey("positions.id"), nullable=False)
    trade_type = Column(String, nullable=False)  # "sell_put" | "buy_put_close" | "assignment" | "sell_call" | "buy_call_close" | "called_away" | "expired"
    strike = Column(Float, nullable=False)
    expiration = Column(String, nullable=False)  # date string
    premium = Column(Float, nullable=False)  # per-share, positive for credits, negative for debits
    fees = Column(Float, nullable=False, default=0.0)
    quantity = Column(Integer, nullable=False, default=1)  # number of contracts
    opened_at = Column(String, nullable=False)  # ISO datetime
    closed_at = Column(String, nullable=True)
    close_reason = Column(String, nullable=True)  # "fifty_pct_target" | "full_expiration" | "rolled" | "closed_early" | "assigned" | "called_away"
    position = relationship("Position", back_populates="trades")
    # One-to-one child row (issue #160). When the trade is deleted (via
    # ``delete_trade``) the compliance row is removed in the same
    # transaction — the row is a snapshot keyed by ``trade_id`` and has no
    # independent existence. ``passive_deletes`` defaults to False because
    # the project does not enable ``PRAGMA foreign_keys=ON``, so the
    # SQL-level ``ondelete="CASCADE"`` would silently no-op; the ORM-level
    # cascade is what we rely on. ``clear_all_journal_data`` does a bulk
    # delete that bypasses ORM cascade entirely — it wipes the child table
    # explicitly first (see :func:`app.services.journal.clear_all_journal_data`).
    entry_compliance = relationship(
        "TradeEntryCompliance",
        back_populates="trade",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PositionNote(Base):
    """Freeform research thesis attached to a single position (issue #280).

    One row per position (``UNIQUE`` on ``position_id``). The ``version``
    column increments on every successful PUT so the frontend can surface
    optimistic-lock style "edited in another tab" warnings; the column
    exists for future use even though v1 does not expose version history.

    Schema frozen in the issue #280 implementation plan §3.2 / §4.3.

    The project has no Alembic — the table is picked up by the existing
    ``Base.metadata.create_all(bind=engine)`` call in :func:`init_db` and
    ``create_all`` is idempotent, so an existing deployment grows the new
    table on next startup without migration overhead. Rollback path is a
    manual ``DROP TABLE position_notes``.
    """

    __tablename__ = "position_notes"

    id = Column(String, primary_key=True)  # UUID4
    position_id = Column(
        String,
        ForeignKey("positions.id"),
        nullable=False,
        index=True,
        unique=True,
    )
    body = Column(Text, nullable=False, default="")  # max 4000 chars enforced at API
    version = Column(Integer, nullable=False, default=1)  # increments on each PUT
    updated_at = Column(String, nullable=False)  # ISO datetime
    updated_by = Column(String, nullable=True)  # nullable in single-user mode


class TradeEntryCompliance(Base):
    """Per-trade entry-rule compliance row (issue #160 / Quality v1 Wave 3).

    One row per evaluated trade. ``trade_id`` is the primary key — the row
    is written once when a ``sell_put`` / ``sell_call`` trade is created and
    is **never updated**. This snapshot-not-reference design preserves the
    historical compliance verdict against the live ``rules_config`` so a
    trader who tightens their entry rules tomorrow does not retroactively
    flag yesterday's compliant trade as non-compliant.

    Field shape locked in the Wave 3 plan §V1-Freeze-1:

    - ``trade_id`` (FK -> trades.id, primary_key) — one row per trade.
    - ``evaluated_at`` — ISO datetime string (matches the codebase's
      no-native-timestamp convention).
    - ``dte_at_entry`` — always derivable, never unknown.
    - ``delta_at_entry`` — nullable; Schwab-imported trades carry None and
      the evaluator marks them ``delta_unknown`` (not non-compliant).
    - ``monthly_return_pct`` — whole-percent, matching ``RulesConfig``.
    - ``earnings_buffer_days`` — nullable; None marks
      ``earnings_buffer_unknown`` (not non-compliant).
    - ``compliant`` — integer 0/1 (SQLite has no native BOOLEAN; matches
      the codebase convention).
    - ``failed_rules`` — JSON-encoded array of locked string literals; see
      :mod:`app.services.entry_compliance` for the vocabulary.
    - ``entry_rules_snapshot`` — JSON-encoded object capturing the relevant
      slice of :class:`app.services.rules_config.EntryRules` at evaluation
      time. Stored as text (not a foreign key to a config version) because
      the config has no version table.

    The project has no Alembic — ``Base.metadata.create_all(bind=engine)``
    is idempotent, so an existing deployment grows the new table on next
    startup without migration overhead. Rollback path is a manual
    ``DROP TABLE trade_entry_compliance``.
    """

    __tablename__ = "trade_entry_compliance"

    trade_id = Column(
        String,
        ForeignKey("trades.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evaluated_at = Column(String, nullable=False)  # ISO datetime
    dte_at_entry = Column(Integer, nullable=False)
    delta_at_entry = Column(Float, nullable=True)
    monthly_return_pct = Column(Float, nullable=False)
    earnings_buffer_days = Column(Integer, nullable=True)
    compliant = Column(Integer, nullable=False)  # 0/1 — SQLite boolean idiom
    failed_rules = Column(Text, nullable=False)  # JSON-encoded array of strings
    entry_rules_snapshot = Column(Text, nullable=False)  # JSON-encoded object
    trade = relationship("Trade", back_populates="entry_compliance")


class WatchlistTicker(Base):
    """A single approved underlying in the trader's watchlist (issue #321).

    The watchlist is the operational form of the wheel-strategy "would I
    voluntarily own this?" gate (PRD #213): the options scanner and downstream
    engines only consider names that appear here. This is the **data + API
    layer only** — scanner integration (PRD #213 R5) and the management UI
    are sibling issues in the V1.6 milestone.

    Storage decision (PRD #213 Q1): a **dedicated table, one row per ticker,
    with ``ticker`` as the primary key** — chosen over co-locating a JSON
    blob in ``app_settings`` (the ``rules_config`` pattern) because a
    watchlist is a *set of members*, not a *map of thresholds*. The PK gives
    idempotency for free (duplicate add → no-op on the existing row; missing
    remove → ``DELETE`` affecting zero rows) and lets v2 per-ticker metadata
    (target price, tags, notes — MVP non-goals) grow as new columns without a
    schema redesign. Rationale recorded in
    ``backend/design-specs/issue-321-watchlist-api-plan.md``.

    ``ticker`` is stored uppercase-normalized; normalization happens at the
    service / API boundary so the PK uniqueness constraint dedupes
    case-insensitively (``aapl`` and ``AAPL`` collapse to one row).

    The project has no Alembic — ``Base.metadata.create_all(bind=engine)`` in
    :func:`init_db` is idempotent, so an existing deployment grows the
    ``watchlist`` table on next startup without a migration. Rollback path is
    a manual ``DROP TABLE watchlist``.
    """

    __tablename__ = "watchlist"

    ticker = Column(String, primary_key=True)  # uppercase-normalized symbol
    added_at = Column(String, nullable=False)  # ISO datetime — audit + stable sort


class QuoteStub(Base):
    """Deterministic underlying quote for the QA stub-pricing layer (issue #349).

    Internal table — never a route response model. Seeded and torn down by
    ``seed-qa`` (cascaded with the synthetic positions). Read only by
    :class:`app.services.market_client.StubSchwabClient` when
    ``settings.pricing_mode == "stub"`` (QA only); the prod path never
    constructs the stub client, so this table stays empty on production.

    One row per ticker (``ticker`` is the primary key). ``last_price`` is the
    synthetic underlying price returned in the Schwab-shaped quote dict.

    The project has no Alembic — ``Base.metadata.create_all(bind=engine)`` is
    idempotent, so an existing deployment grows the table on next startup.
    Rollback path is a manual ``DROP TABLE quote_stubs``.
    """

    __tablename__ = "quote_stubs"

    ticker = Column(String, primary_key=True)  # underlying symbol
    last_price = Column(Float, nullable=False)  # synthetic last price


class OptionMarkStub(Base):
    """Deterministic option mark for the QA stub-pricing layer (issue #349).

    Internal table — never a route response model. Seeded and torn down by
    ``seed-qa``. Read only by :class:`app.services.market_client.StubSchwabClient`
    when ``settings.pricing_mode == "stub"`` (QA only).

    One row per ``(ticker, strike, expiration, option_type)`` leg. The stub
    client reassembles these rows into a Schwab-shaped ``callExpDateMap`` /
    ``putExpDateMap`` chain so ``build_option_leg_index`` parses them unchanged.
    ``delta`` is nullable: omitting it (and the row entirely) lets an archetype
    model the "no live option mark" degrade path.

    Rollback path is a manual ``DROP TABLE option_mark_stubs``.
    """

    __tablename__ = "option_mark_stubs"

    id = Column(String, primary_key=True)  # UUID4
    ticker = Column(String, nullable=False, index=True)
    strike = Column(Float, nullable=False)
    expiration = Column(String, nullable=False)  # YYYY-MM-DD
    option_type = Column(String, nullable=False)  # "call" | "put"
    mid = Column(Float, nullable=False)  # synthetic option mid (per-share)
    delta = Column(Float, nullable=True)  # signed live delta, nullable


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
