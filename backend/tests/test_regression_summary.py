"""Tests for the plain-English regression summary generator (issue #280).

Covers the four worked examples from frontend/design-specs/issue-280-stock-research.md
§4 Section E (SOFI, AAPL, TLT, idiosyncratic biotech) plus the rule-3 sign-aware
phrasing branches and the sector-omitted special handling.
"""

from __future__ import annotations

import pytest

from app.services.regression_summary import (
    SummaryFactor,
    build_regression_summary,
)


# --- Helpers ---------------------------------------------------------------


def _factor(
    name: str,
    *,
    beta: float | None,
    p_value: float | None,
    contribution: float,
) -> SummaryFactor:
    """Convenience constructor for SummaryFactor TypedDict instances."""
    return {  # type: ignore[return-value]
        "name": name,  # type: ignore[typeddict-item]
        "beta": beta,
        "p_value": p_value,
        "contribution": contribution,
    }


# --- Spec example fixtures -------------------------------------------------


SOFI_FACTORS: list[SummaryFactor] = [
    _factor("market", beta=1.42, p_value=0.001, contribution=0.60),
    # Sector contribution below the 0.10 threshold so only rates surfaces
    # as a meaningful secondary, matching the spec example string.
    _factor("sector", beta=0.78, p_value=0.04, contribution=0.08),
    _factor("rates", beta=-0.61, p_value=0.02, contribution=0.15),
    _factor("idiosyncratic", beta=None, p_value=None, contribution=0.17),
]


AAPL_FACTORS: list[SummaryFactor] = [
    _factor("market", beta=1.10, p_value=0.001, contribution=0.55),
    _factor("sector", beta=0.62, p_value=0.03, contribution=0.18),
    # Rates beta below the |beta|>0.5 threshold → not meaningful.
    _factor("rates", beta=-0.12, p_value=0.40, contribution=0.05),
    _factor("idiosyncratic", beta=None, p_value=None, contribution=0.22),
]


TLT_FACTORS: list[SummaryFactor] = [
    # Rates dominate (0.30 < contribution <= 0.50 → "Primarily"); the
    # remaining factors are non-meaningful so the fallback "market exposure
    # is minor" clause fires.
    _factor("market", beta=0.20, p_value=0.30, contribution=0.20),
    _factor("sector", beta=0.10, p_value=0.20, contribution=0.15),
    _factor("rates", beta=-1.80, p_value=0.001, contribution=0.40),
    _factor("idiosyncratic", beta=None, p_value=None, contribution=0.25),
]


BIOTECH_FACTORS: list[SummaryFactor] = [
    # Binary-event biotech: most of variance is unexplained.
    _factor("market", beta=0.4, p_value=0.20, contribution=0.18),
    _factor("sector", beta=0.3, p_value=0.20, contribution=0.12),
    _factor("rates", beta=-0.10, p_value=0.50, contribution=0.10),
    _factor("idiosyncratic", beta=None, p_value=None, contribution=0.60),
]


# --- Spec example tests ----------------------------------------------------


@pytest.mark.unit
def test_spec_example_sofi_rate_sensitive_financial() -> None:
    """SOFI: dominant market, secondary rate exposure (negative)."""
    out = build_regression_summary(
        factors=SOFI_FACTORS,
        r_squared=0.83,
        sample_size=252,
        sector_omitted=False,
    )
    assert out == (
        "Mostly market-driven; rate exposure is meaningful and negative. "
        "R²=0.83 over 252 trading days."
    )


@pytest.mark.unit
def test_spec_example_aapl_low_rates_tech_heavy() -> None:
    """AAPL: dominant market, secondary sector adds positively."""
    out = build_regression_summary(
        factors=AAPL_FACTORS,
        r_squared=0.78,
        sample_size=252,
        sector_omitted=False,
    )
    assert out == (
        "Mostly market-driven; sector exposure adds positively. "
        "R²=0.78 over 252 trading days."
    )


@pytest.mark.unit
def test_spec_example_tlt_rate_tracker() -> None:
    """TLT: dominant rates, market exposure is minor (non-meaningful fallback)."""
    out = build_regression_summary(
        factors=TLT_FACTORS,
        r_squared=0.91,
        sample_size=252,
        sector_omitted=False,
    )
    assert out == (
        "Primarily rate-driven; market exposure is minor. "
        "R²=0.91 over 252 trading days."
    )


@pytest.mark.unit
def test_spec_example_idiosyncratic_biotech() -> None:
    """Biotech: idiosyncratic-dominant special form."""
    out = build_regression_summary(
        factors=BIOTECH_FACTORS,
        r_squared=0.40,
        sample_size=252,
        sector_omitted=False,
    )
    assert out == (
        "Mostly idiosyncratic — 60% of variance unexplained by "
        "market/sector/rates. R²=0.40 over 252 trading days."
    )


# --- Rule branch coverage --------------------------------------------------


@pytest.mark.unit
def test_rule_2_primarily_when_dominant_between_30_and_50_pct() -> None:
    """Rule 2: ``Primarily`` label kicks in for 0.30 < dominant <= 0.50."""
    factors = [
        _factor("market", beta=1.0, p_value=0.001, contribution=0.40),
        _factor("sector", beta=0.2, p_value=0.30, contribution=0.20),
        _factor("rates", beta=-0.1, p_value=0.40, contribution=0.10),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.30),
    ]
    out = build_regression_summary(
        factors=factors, r_squared=0.70, sample_size=252
    )
    assert out.startswith("Primarily market-driven")


@pytest.mark.unit
def test_rule_2_diversified_when_no_factor_above_30_pct() -> None:
    """Rule 2: ``Diversified driver mix`` when no factor dominates.

    Boundary case: dominant contribution at exactly 0.30 should still
    produce the diversified label (>0.30 is required to escape it).
    """
    factors = [
        _factor("market", beta=0.4, p_value=0.10, contribution=0.30),
        _factor("sector", beta=0.3, p_value=0.10, contribution=0.25),
        _factor("rates", beta=-0.2, p_value=0.10, contribution=0.20),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.25),
    ]
    out = build_regression_summary(
        factors=factors, r_squared=0.70, sample_size=252
    )
    assert out.startswith("Diversified driver mix")


@pytest.mark.unit
def test_rule_3_positive_beta_on_rates_renders_meaningful_and_positive() -> None:
    """Sign-aware: positive rate beta produces ``...and positive``."""
    factors = [
        _factor("market", beta=1.0, p_value=0.001, contribution=0.55),
        _factor("rates", beta=0.7, p_value=0.01, contribution=0.20),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.25),
    ]
    out = build_regression_summary(
        factors=factors, r_squared=0.75, sample_size=252
    )
    assert "rate exposure is meaningful and positive" in out


@pytest.mark.unit
def test_rule_3_negative_beta_on_sector_renders_detracts() -> None:
    """Sign-aware: negative sector beta produces ``sector exposure detracts``."""
    factors = [
        _factor("market", beta=1.0, p_value=0.001, contribution=0.60),
        _factor("sector", beta=-0.65, p_value=0.04, contribution=0.18),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.22),
    ]
    out = build_regression_summary(
        factors=factors, r_squared=0.78, sample_size=252
    )
    assert "sector exposure detracts" in out


@pytest.mark.unit
def test_rule_3_non_meaningful_factor_is_excluded() -> None:
    """A factor with p>0.05 is dropped from the meaningful list."""
    factors = [
        _factor("market", beta=1.0, p_value=0.001, contribution=0.60),
        _factor("sector", beta=0.7, p_value=0.50, contribution=0.15),  # p too high
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.25),
    ]
    out = build_regression_summary(
        factors=factors, r_squared=0.75, sample_size=252
    )
    # No qualifying meaningful factor → fallback "market exposure is minor"?
    # No — market is dominant. The non-dominant non-meaningful sector falls
    # through to the "minor" fallback because dominant > 0.50.
    assert out == (
        "Mostly market-driven; sector exposure is minor. "
        "R²=0.75 over 252 trading days."
    )


# --- Sector-omitted branch -------------------------------------------------


@pytest.mark.unit
def test_sector_omitted_skips_sector_clause() -> None:
    """When the sector factor is omitted, the rules skip any sector clause."""
    factors = [
        _factor("market", beta=1.2, p_value=0.001, contribution=0.65),
        _factor("rates", beta=-0.7, p_value=0.02, contribution=0.20),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.15),
    ]
    out = build_regression_summary(
        factors=factors,
        r_squared=0.85,
        sample_size=252,
        sector_omitted=True,
    )
    assert "sector" not in out.lower()
    assert "rate exposure is meaningful and negative" in out


@pytest.mark.unit
def test_sector_omitted_idiosyncratic_uses_two_factor_basket_phrase() -> None:
    """Idiosyncratic-dominant + sector-omitted lists market/rates only."""
    factors = [
        _factor("market", beta=0.3, p_value=0.30, contribution=0.20),
        _factor("rates", beta=-0.1, p_value=0.40, contribution=0.10),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.70),
    ]
    out = build_regression_summary(
        factors=factors,
        r_squared=0.30,
        sample_size=252,
        sector_omitted=True,
    )
    assert "market/rates" in out
    assert "market/sector/rates" not in out


# --- Format / cap coverage -------------------------------------------------


@pytest.mark.unit
def test_r_squared_is_two_decimals() -> None:
    """R² renders with two decimals (matches spec examples)."""
    factors = [
        _factor("market", beta=1.0, p_value=0.01, contribution=0.55),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.45),
    ]
    out = build_regression_summary(factors=factors, r_squared=0.123456, sample_size=200)
    assert "R²=0.12 over 200 trading days" in out


@pytest.mark.unit
def test_summary_is_at_most_120_characters_under_normal_conditions() -> None:
    """All four spec examples + the rule-branch tests stay under 120 chars."""
    cases = [SOFI_FACTORS, AAPL_FACTORS, TLT_FACTORS, BIOTECH_FACTORS]
    for c in cases:
        out = build_regression_summary(factors=c, r_squared=0.80, sample_size=252)
        assert len(out) <= 120, f"summary exceeds 120 chars: {out!r}"


@pytest.mark.unit
def test_empty_factors_returns_safe_fallback() -> None:
    """Defensive: empty factor list still returns a deterministic string."""
    out = build_regression_summary(
        factors=[], r_squared=0.0, sample_size=0, sector_omitted=False
    )
    assert "Insufficient data" in out
    assert "R²=0.00 over 0 trading days" in out


@pytest.mark.unit
@pytest.mark.parametrize(
    "p_value, abs_beta, contribution, expected_meaningful",
    [
        (0.04, 0.6, 0.15, True),
        (0.06, 0.6, 0.15, False),  # p too high
        (0.04, 0.4, 0.15, False),  # |beta| too low
        (0.04, 0.6, 0.05, False),  # contribution too low
    ],
)
def test_rule_3_predicate_thresholds(
    p_value: float, abs_beta: float, contribution: float, expected_meaningful: bool
) -> None:
    """Rule 3 predicate is strict on all three thresholds."""
    factors = [
        _factor("market", beta=1.0, p_value=0.001, contribution=0.60),
        _factor(
            "rates",
            beta=-abs_beta,
            p_value=p_value,
            contribution=contribution,
        ),
        _factor("idiosyncratic", beta=None, p_value=None, contribution=0.20),
    ]
    out = build_regression_summary(
        factors=factors, r_squared=0.78, sample_size=252
    )
    if expected_meaningful:
        assert "rate exposure is meaningful and negative" in out
    else:
        # Non-meaningful → either no rate clause or "minor" fallback.
        assert "rate exposure is meaningful and negative" not in out
