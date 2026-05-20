"""Unit tests for the ``rules_config`` keystone module (issue #156).

Covers the schema (PRD #209 catalog defaults, range validators) and the full
:func:`load_rules_config` reader-behavior matrix: missing row, valid full
object, valid partial object (merge-over-defaults), malformed JSON, a single
out-of-range field, an inverted range, and the never-raises guarantee.

These are pure DB-row tests — they use an in-memory SQLite session directly
(not the ``client`` TestClient fixture) so the reader can be exercised against
hand-crafted ``app_settings`` values.
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import AppSetting, Base
from app.services.rules_config import (
    DEFAULT_RULES_CONFIG,
    RULES_CONFIG_KEY,
    RULES_CONFIG_SCHEMA_VERSION,
    EntryRules,
    ManagementTriggers,
    PositionRules,
    RangeRule,
    RiskRules,
    RulesConfig,
    UniverseRules,
    load_rules_config,
)


@pytest.fixture()
def db():
    """An in-memory SQLite session with the full schema created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()


def _store(db, value: str) -> None:
    """Write a raw ``rules_config`` value into ``app_settings``."""
    db.add(AppSetting(key=RULES_CONFIG_KEY, value=value))
    db.commit()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_module_constants():
    """The key and schema-version constants match the ADR-002 spec."""
    assert RULES_CONFIG_KEY == "rules_config"
    assert RULES_CONFIG_SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# DEFAULT_RULES_CONFIG equals the PRD #209 catalog
# ---------------------------------------------------------------------------


def test_default_config_universe_matches_catalog():
    """Universe defaults equal PRD #209 §R2."""
    u = DEFAULT_RULES_CONFIG.universe
    assert u.min_open_interest == 500
    assert u.max_bid_ask_spread_pct == 10.0
    assert u.min_iv_rank == 30.0
    assert u.min_iv_percentile is None


def test_default_config_entry_matches_catalog():
    """Entry defaults equal the reconciled PRD #209 §R3 catalog."""
    e = DEFAULT_RULES_CONFIG.entry
    assert (e.dte_range.min, e.dte_range.max) == (21, 45)
    assert (e.delta_range_csp.min, e.delta_range_csp.max) == (0.20, 0.30)
    assert (e.delta_range_cc.min, e.delta_range_cc.max) == (0.20, 0.35)
    assert e.min_monthly_return_pct == 2.0
    assert e.earnings_buffer_days == 7
    assert e.min_call_distance_pct == 5.0
    assert e.min_call_distance_from_cost_basis_pct == 0.0


def test_default_config_position_matches_catalog():
    """Position defaults equal PRD #209 §R4."""
    p = DEFAULT_RULES_CONFIG.position
    assert p.sizing_cap_pct == 25.0
    assert p.max_ticker_concentration_pct == 25.0
    assert p.max_open_positions is None


def test_default_config_risk_matches_catalog():
    """Risk defaults equal PRD #209 §R5."""
    r = DEFAULT_RULES_CONFIG.risk
    assert r.loss_review_threshold_pct == -15.0
    assert r.hard_max_loss_pct is None
    assert r.max_consecutive_rolls is None


def test_default_config_management_matches_catalog():
    """Management defaults equal PRD #209 §R6."""
    m = DEFAULT_RULES_CONFIG.management
    assert m.profit_review_pct == 50.0
    assert m.dte_review_days == 21
    assert m.expiration_warning_days == 7
    assert m.assignment_risk_review == "High"


def test_default_config_carries_schema_version():
    """The top-level model carries the schema-version integer."""
    assert DEFAULT_RULES_CONFIG.schema_version == RULES_CONFIG_SCHEMA_VERSION
    dumped = DEFAULT_RULES_CONFIG.model_dump()
    assert dumped["schema_version"] == 1


# ---------------------------------------------------------------------------
# Validators reject out-of-range values
# ---------------------------------------------------------------------------


def test_validator_rejects_negative_dte():
    """A negative DTE minimum is rejected."""
    with pytest.raises(ValidationError):
        EntryRules(dte_range=RangeRule(min=-1, max=45))


def test_validator_rejects_delta_above_one():
    """A delta above 1.0 is rejected."""
    with pytest.raises(ValidationError):
        EntryRules(delta_range_csp=RangeRule(min=0.2, max=1.5))


def test_validator_rejects_delta_below_zero():
    """A negative delta bound is rejected."""
    with pytest.raises(ValidationError):
        EntryRules(delta_range_csp=RangeRule(min=-0.1, max=0.3))


def test_validator_rejects_inverted_range():
    """A range with ``min >= max`` is rejected."""
    with pytest.raises(ValidationError):
        RangeRule(min=45, max=21)
    with pytest.raises(ValidationError):
        RangeRule(min=30, max=30)


def test_validator_rejects_positive_loss_threshold():
    """A loss-review threshold above zero is rejected — a loss is not a gain."""
    with pytest.raises(ValidationError):
        RiskRules(loss_review_threshold_pct=5.0)


def test_validator_rejects_profit_review_over_100():
    """A profit-review percent above 100 is rejected."""
    with pytest.raises(ValidationError):
        ManagementTriggers(profit_review_pct=150.0)


def test_validator_rejects_zero_max_open_positions():
    """A max-open-positions cap below 1 is rejected when set."""
    with pytest.raises(ValidationError):
        PositionRules(max_open_positions=0)


def test_validator_rejects_negative_open_interest():
    """A negative open-interest floor is rejected."""
    with pytest.raises(ValidationError):
        UniverseRules(min_open_interest=-1)


def test_validator_rejects_out_of_range_sizing_cap_pct():
    """A sizing cap percentage of zero or less is rejected."""
    with pytest.raises(ValidationError):
        PositionRules(sizing_cap_pct=0.0)


# ---------------------------------------------------------------------------
# Validators ACCEPT the unset optionals as None (ADR-002 OQ1 / PRD #209 Q1)
# ---------------------------------------------------------------------------


def test_unset_optionals_accept_none():
    """The four PRD #209 "unset" rules are valid as ``None`` — no enforcement.

    ``max_open_positions``, ``hard_max_loss_pct``, ``max_consecutive_rolls`` and
    ``min_iv_percentile`` are persisted/validated only. No engine in #156 acts
    on a ``None`` value — concrete values are PRD #209 Q1 / ADR-002 OQ1,
    deferred to the trader.
    """
    cfg = RulesConfig()
    assert cfg.position.max_open_positions is None
    assert cfg.risk.hard_max_loss_pct is None
    assert cfg.risk.max_consecutive_rolls is None
    assert cfg.universe.min_iv_percentile is None
    # And they accept a concrete value too, so a future trader-set value works.
    assert PositionRules(max_open_positions=5).max_open_positions == 5
    assert RiskRules(hard_max_loss_pct=-50.0).hard_max_loss_pct == -50.0


# ---------------------------------------------------------------------------
# load_rules_config — missing row
# ---------------------------------------------------------------------------


def test_load_missing_row_returns_defaults(db, caplog):
    """No ``rules_config`` row → the full default config + an INFO log."""
    with caplog.at_level(logging.INFO):
        cfg = load_rules_config(db)
    assert cfg == DEFAULT_RULES_CONFIG
    assert any("default trading rules" in r.message for r in caplog.records)


def test_load_empty_value_returns_defaults(db):
    """An empty-string stored value is treated as missing → defaults."""
    _store(db, "   ")
    assert load_rules_config(db) == DEFAULT_RULES_CONFIG


# ---------------------------------------------------------------------------
# load_rules_config — valid full object
# ---------------------------------------------------------------------------


def test_load_valid_full_object_returns_stored_values(db):
    """A valid full stored object → exactly those values are returned."""
    stored = {
        "schema_version": 1,
        "universe": {
            "min_open_interest": 1000,
            "max_bid_ask_spread_pct": 5.0,
            "min_iv_rank": 40.0,
            "min_iv_percentile": 50.0,
        },
        "entry": {
            "dte_range": {"min": 30, "max": 60},
            "delta_range_csp": {"min": 0.10, "max": 0.25},
            "delta_range_cc": {"min": 0.15, "max": 0.40},
            "min_monthly_return_pct": 3.5,
            "earnings_buffer_days": 10,
            "min_call_distance_pct": 8.0,
            "min_call_distance_from_cost_basis_pct": 2.0,
        },
        "position": {
            "sizing_cap_pct": 40.0,
            "max_ticker_concentration_pct": 15.0,
            "max_open_positions": 10,
        },
        "risk": {
            "loss_review_threshold_pct": -20.0,
            "hard_max_loss_pct": -50.0,
            "max_consecutive_rolls": 3,
        },
        "management": {
            "profit_review_pct": 75.0,
            "dte_review_days": 30,
            "expiration_warning_days": 5,
            "assignment_risk_review": "Medium",
        },
    }
    _store(db, json.dumps(stored))
    cfg = load_rules_config(db)

    assert cfg.universe.min_open_interest == 1000
    assert cfg.entry.dte_range.min == 30 and cfg.entry.dte_range.max == 60
    assert cfg.entry.min_monthly_return_pct == 3.5
    assert cfg.position.sizing_cap_pct == 40.0
    assert cfg.position.max_open_positions == 10
    assert cfg.risk.hard_max_loss_pct == -50.0
    assert cfg.management.assignment_risk_review == "Medium"


# ---------------------------------------------------------------------------
# load_rules_config — valid partial object (merge-over-defaults)
# ---------------------------------------------------------------------------


def test_load_partial_object_merges_over_defaults(db):
    """A partial stored object → stored fields honored, the rest defaulted."""
    _store(db, json.dumps({"entry": {"min_monthly_return_pct": 4.0}}))
    cfg = load_rules_config(db)

    # The one stored field is honored.
    assert cfg.entry.min_monthly_return_pct == 4.0
    # Sibling entry fields fall back to the catalog default.
    assert cfg.entry.dte_range.min == 21 and cfg.entry.dte_range.max == 45
    # The four other groups are entirely defaulted.
    assert cfg.universe == DEFAULT_RULES_CONFIG.universe
    assert cfg.position == DEFAULT_RULES_CONFIG.position
    assert cfg.risk == DEFAULT_RULES_CONFIG.risk
    assert cfg.management == DEFAULT_RULES_CONFIG.management


def test_load_partial_group_only(db):
    """An older build that stored only ``entry`` → other four groups defaulted."""
    _store(db, json.dumps({"entry": {"dte_range": {"min": 25, "max": 50}}}))
    cfg = load_rules_config(db)
    assert (cfg.entry.dte_range.min, cfg.entry.dte_range.max) == (25, 50)
    assert cfg.position == DEFAULT_RULES_CONFIG.position


# ---------------------------------------------------------------------------
# load_rules_config — malformed JSON
# ---------------------------------------------------------------------------


def test_load_malformed_json_returns_defaults_and_warns(db, caplog):
    """Malformed JSON → defaults + a generic WARNING that leaks no exception text."""
    _store(db, "{not valid json")
    with caplog.at_level(logging.WARNING):
        cfg = load_rules_config(db)
    assert cfg == DEFAULT_RULES_CONFIG

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING log on malformed JSON"
    joined = " ".join(r.message for r in warnings)
    assert "not valid JSON" in joined
    # CLAUDE.md: no str(e) — the Python JSON-decode error text must not leak.
    assert "Expecting" not in joined
    assert "line 1" not in joined
    assert "char" not in joined


def test_load_non_object_json_returns_defaults(db):
    """Valid JSON that is not an object (e.g. a list) → defaults."""
    _store(db, json.dumps([1, 2, 3]))
    assert load_rules_config(db) == DEFAULT_RULES_CONFIG


# ---------------------------------------------------------------------------
# load_rules_config — single out-of-range field (per-field fallback)
# ---------------------------------------------------------------------------


def test_load_single_bad_field_falls_back_that_field_only(db):
    """One out-of-range field reverts to its default; the rest is honored."""
    _store(
        db,
        json.dumps(
            {
                "entry": {
                    "min_monthly_return_pct": -9,  # invalid — must be >= 0
                    "earnings_buffer_days": 14,  # valid — must be honored
                }
            }
        ),
    )
    cfg = load_rules_config(db)
    # The bad field reverted to the catalog default.
    assert cfg.entry.min_monthly_return_pct == 2.0
    # The valid sibling field was honored.
    assert cfg.entry.earnings_buffer_days == 14


def test_load_inverted_range_reverts_range_only(db, caplog):
    """An inverted ``dte_range`` reverts as a unit; other fields are honored."""
    _store(
        db,
        json.dumps(
            {
                "entry": {
                    "dte_range": {"min": 99, "max": 1},  # inverted — invalid
                    "min_monthly_return_pct": 3.0,  # valid — honored
                }
            }
        ),
    )
    with caplog.at_level(logging.WARNING):
        cfg = load_rules_config(db)
    # The inverted range reverted to the catalog default.
    assert (cfg.entry.dte_range.min, cfg.entry.dte_range.max) == (21, 45)
    # The valid sibling field was honored.
    assert cfg.entry.min_monthly_return_pct == 3.0
    # A WARNING names the dropped field but leaks no stored value.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("entry.dte_range" in r.message for r in warnings)


def test_load_bad_field_in_one_group_does_not_poison_others(db):
    """A bad field in ``risk`` does not discard a valid ``position`` group."""
    _store(
        db,
        json.dumps(
            {
                "risk": {"loss_review_threshold_pct": 99},  # invalid (> 0)
                "position": {"sizing_cap_pct": 12.34},  # valid
            }
        ),
    )
    cfg = load_rules_config(db)
    assert cfg.risk.loss_review_threshold_pct == -15.0  # reverted
    assert cfg.position.sizing_cap_pct == 12.34  # honored


# ---------------------------------------------------------------------------
# load_rules_config — never raises
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored_value",
    [
        "{not json",
        "",
        "null",
        "42",
        '"a string"',
        json.dumps([1, 2]),
        json.dumps({"entry": "not an object"}),
        json.dumps({"entry": {"dte_range": {"min": -5, "max": -1}}}),
        json.dumps({"universe": {"min_open_interest": "abc"}}),
        json.dumps({"position": {"sizing_cap_pct": -10.0}}),
        json.dumps({"unknown_group": {"foo": 1}}),
        json.dumps({"entry": {"unknown_field": 123}}),
    ],
)
def test_load_never_raises(db, stored_value):
    """``load_rules_config`` never raises, whatever the stored value is."""
    _store(db, stored_value)
    cfg = load_rules_config(db)  # must not raise
    assert isinstance(cfg, RulesConfig)


# ---------------------------------------------------------------------------
# Documented-as-comment: enforcement of the unset rules is out of scope.
#
# ``max_open_positions`` / ``hard_max_loss_pct`` / ``max_consecutive_rolls`` /
# ``min_iv_percentile`` are persisted and validated by RulesConfig (covered by
# ``test_unset_optionals_accept_none`` above), but NO engine enforces a None or
# a set value for them in #156. Concrete enforced values and their semantics
# are PRD #209 open question Q1 / ADR-002 OQ1, deferred to the trader. There is
# intentionally no enforcement test here because there is no enforcement to
# test — inventing one would be a stop-and-ask violation.
# ---------------------------------------------------------------------------
