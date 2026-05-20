"""Static guard — no hard-coded trading-rule constant survives (issue #156).

After the engine wiring, every entry / position / risk / management rule value
must come from ``rules_config`` — never from a module constant or a literal
default. This test fails CI if a migrated constant reappears, so an incomplete
or reverted migration cannot land silently.

Intentionally retained literals — ``WHEEL_MONTHLY_PREMIUM_PCT``,
``WHEEL_BE_MULTIPLIERS``, ``LARGE_LOSER_DOLLAR_THRESHOLD``,
``TOKEN_EXPIRING_DAYS``, ``MAX_ACTIONS``, ``ITM_SHORT_DTE_CAP`` — are internal
heuristics and display caps, explicitly NOT trader-facing trading rules
(ADR-002 "We will NOT"). The allow-list below is kept narrow so they do not
trip the guard.

``LARGE_LOSER_PCT_THRESHOLD`` is **no longer** a retained heuristic: issue #235
migrated it to ``rules_config.risk.loss_review_threshold_pct``. It is in the
banned set for both the ``action_engine`` and the ``positions`` router so a
reverted migration cannot land silently. Only the *dollar* large-loser
threshold remains a hardcoded heuristic.
"""

from __future__ import annotations

import inspect

from app.models import schemas
from app.models.schemas import OptionScanRequest
from app.routers import positions as positions_router
from app.services import action_engine, recovery_engine


# The rule constants that issue #156 removed. Each must no longer exist as a
# module attribute on its engine.
def test_recovery_engine_default_sizing_cap_constant_removed():
    """``DEFAULT_SIZING_CAP_DOLLARS`` no longer exists on the recovery engine."""
    assert not hasattr(recovery_engine, "DEFAULT_SIZING_CAP_DOLLARS"), (
        "DEFAULT_SIZING_CAP_DOLLARS must be gone — the sizing cap is resolved "
        "from rules_config.position.sizing_cap_pct (issue #234)."
    )
    assert "DEFAULT_SIZING_CAP_DOLLARS" not in recovery_engine.__all__


def test_action_engine_itm_short_dte_max_constant_removed():
    """``ITM_SHORT_DTE_MAX_DTE`` no longer exists on the action engine."""
    assert not hasattr(action_engine, "ITM_SHORT_DTE_MAX_DTE"), (
        "ITM_SHORT_DTE_MAX_DTE must be gone — the threshold is resolved from "
        "rules_config.management.expiration_warning_days (issue #156)."
    )


def test_large_loser_pct_threshold_constant_removed():
    """``LARGE_LOSER_PCT_THRESHOLD`` no longer exists on either consumer.

    Issue #235 migrated the percentage flag threshold to
    ``rules_config.risk.loss_review_threshold_pct``. Only the *dollar*
    large-loser threshold remains a hardcoded heuristic.
    """
    for module, label in (
        (action_engine, "action engine"),
        (positions_router, "positions router"),
    ):
        assert not hasattr(module, "LARGE_LOSER_PCT_THRESHOLD"), (
            f"LARGE_LOSER_PCT_THRESHOLD must be gone from the {label} — the "
            "percentage flag threshold is resolved from "
            "rules_config.risk.loss_review_threshold_pct (issue #235)."
        )
        # The retained dollar heuristic must still be present.
        assert hasattr(module, "LARGE_LOSER_DOLLAR_THRESHOLD"), (
            f"LARGE_LOSER_DOLLAR_THRESHOLD must remain on the {label} — it is "
            "an intentionally-retained absolute-loss heuristic (ADR-002)."
        )


def test_option_scan_request_rule_fields_default_to_none():
    """The seven ``OptionScanRequest`` rule fields default to ``None``.

    A ``None`` default means the value is resolved from ``rules_config`` by the
    scan router — no hard-coded literal default remains on the contract.
    """
    fields = OptionScanRequest.model_fields
    rule_fields = [
        "min_dte",
        "max_dte",
        "min_return_pct",
        "min_call_distance_pct",
        "max_delta",
        "min_delta",
        "exclude_earnings_dte",
    ]
    for name in rule_fields:
        assert name in fields, f"{name} missing from OptionScanRequest"
        assert fields[name].default is None, (
            f"OptionScanRequest.{name} must default to None (resolved from "
            f"rules_config), not a hard-coded literal."
        )


def test_option_scan_request_has_universe_rule_fields():
    """``OptionScanRequest`` carries the universe-rule fields, all default ``None``."""
    fields = OptionScanRequest.model_fields
    for name in ("min_open_interest", "max_bid_ask_spread_pct", "min_iv_rank"):
        assert name in fields, f"{name} missing from OptionScanRequest"
        assert fields[name].default is None


def test_no_migrated_constant_name_in_source():
    """A source-text scan confirms the migrated constant names are gone.

    The allow-list is intentionally narrow: the remaining retained heuristics
    (WHEEL_*, LARGE_LOSER_DOLLAR_THRESHOLD, etc.) are not in the banned set,
    so they do not trip this guard. ``LARGE_LOSER_PCT_THRESHOLD`` *is* banned
    (issue #235) on both the action engine and the positions router.
    """
    banned = {
        "schemas": (schemas, []),
        "action_engine": (
            action_engine,
            ["ITM_SHORT_DTE_MAX_DTE", "LARGE_LOSER_PCT_THRESHOLD"],
        ),
        "recovery_engine": (recovery_engine, ["DEFAULT_SIZING_CAP_DOLLARS"]),
        "positions_router": (positions_router, ["LARGE_LOSER_PCT_THRESHOLD"]),
    }
    for label, (module, banned_names) in banned.items():
        source = inspect.getsource(module)
        for name in banned_names:
            # Allow the name to appear in a comment that explains the removal
            # (e.g. "resolved from rules_config" docstrings reference history).
            for line in source.splitlines():
                stripped = line.strip()
                if name in stripped and not (
                    stripped.startswith("#")
                    or stripped.startswith('"')
                    or stripped.startswith("'")
                    or "rules_config" in stripped
                ):
                    raise AssertionError(
                        f"{label}: migrated rule constant '{name}' still "
                        f"referenced in code: {stripped!r}"
                    )
