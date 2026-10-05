"""Unit tests for :mod:`app.services.covered_call_rule` (#456).

The covered-call distance rule is ``strike >= cost_basis * (1 + T/100)``
where ``T`` is ``min_call_distance_pct``. This module owns the required-strike
math (cent precision, exact decimal arithmetic), the raw rejection-string
emitter + parser, and the canonical human sentence shared by the scanner,
``rejection_messages`` and ``rejection_relax``.

Pure functions only — no DB, no TestClient, no network.
"""

import pytest

from app.services.covered_call_rule import (
    fails_10pct_raw,
    fails_10pct_sentence,
    format_threshold_pct,
    meets_call_distance,
    parse_fails_10pct,
    required_call_strike,
)


# -- required_call_strike ----------------------------------------------------


@pytest.mark.unit
def test_required_strike_basis_1321_is_1453():
    assert required_call_strike(13.21, 10.0) == 14.53


@pytest.mark.unit
def test_required_strike_basis_10_is_exactly_11():
    # Raw float math gives 11.000000000000002 — the helper must not drift.
    assert required_call_strike(10.0, 10.0) == 11.0


# -- meets_call_distance -----------------------------------------------------


@pytest.mark.unit
def test_meets_strike_below_basis_fails():
    assert meets_call_distance(12.50, 13.21, 10.0) is False


@pytest.mark.unit
def test_meets_strike_between_basis_and_110_fails():
    assert meets_call_distance(14.50, 13.21, 10.0) is False


@pytest.mark.unit
def test_meets_strike_exactly_110_passes():
    assert meets_call_distance(11.00, 10.00, 10.0) is True
    assert meets_call_distance(14.53, 13.21, 10.0) is True


@pytest.mark.unit
def test_meets_strike_above_110_passes():
    assert meets_call_distance(15.00, 13.21, 10.0) is True


@pytest.mark.unit
def test_meets_strike_one_cent_under_fails():
    assert meets_call_distance(14.52, 13.21, 10.0) is False


@pytest.mark.unit
def test_threshold_uses_param_not_literal():
    # 13.21 * 1.075 = 14.20075 -> $14.20
    assert required_call_strike(13.21, 7.5) == 14.20
    assert meets_call_distance(14.20, 13.21, 7.5) is True
    assert meets_call_distance(14.50, 13.21, 7.5) is True
    assert meets_call_distance(14.19, 13.21, 7.5) is False


# -- format_threshold_pct ----------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [(10.0, "10"), (7.5, "7.5"), (7.25, "7.25"), (0, "0"), (110.0, "110")],
)
def test_format_threshold_pct(value, expected):
    assert format_threshold_pct(value) == expected


# -- raw string emitter + parser ---------------------------------------------


@pytest.mark.unit
def test_fails_10pct_raw_format_frozen():
    assert fails_10pct_raw(14.50, 13.21, 10.0) == (
        "fails_10pct_rule: strike 9.8% above basis, requires 10.0% "
        "(strike $14.50, basis $13.21, min strike $14.53)"
    )


@pytest.mark.unit
def test_parse_new_format_extracts_strike_basis_min_strike():
    parsed = parse_fails_10pct(
        "fails_10pct_rule: strike 9.8% above basis, requires 10.0% "
        "(strike $14.50, basis $13.21, min strike $14.53)"
    )
    assert parsed == {
        "pct": 9.8,
        "min": 10.0,
        "strike": 14.50,
        "basis": 13.21,
        "min_strike": 14.53,
    }


@pytest.mark.unit
def test_parse_legacy_format_has_no_dollar_fields():
    parsed = parse_fails_10pct(
        "fails_10pct_rule: strike 5.0% above basis, requires 10.0%"
    )
    assert parsed == {
        "pct": 5.0,
        "min": 10.0,
        "strike": None,
        "basis": None,
        "min_strike": None,
    }


@pytest.mark.unit
def test_parse_garbled_returns_none():
    assert parse_fails_10pct("fails_10pct_rule: some garbled message") is None


# -- canonical sentence ------------------------------------------------------


@pytest.mark.unit
def test_sentence_above_wording():
    assert fails_10pct_sentence(14.50, 13.21, 10.0, 9.8, 14.53) == (
        "Strike $14.50 is 9.8% above your $13.21 basis. "
        "Your 10% rule needs a strike of at least $14.53."
    )


@pytest.mark.unit
def test_sentence_below_wording_renders_abs():
    assert fails_10pct_sentence(12.50, 13.21, 10.0, -5.4, 14.53) == (
        "Strike $12.50 is 5.4% below your $13.21 basis. "
        "Your 10% rule needs a strike of at least $14.53."
    )


@pytest.mark.unit
def test_sentence_hair_below_basis_reads_below_not_negative_zero():
    # A strike a hair under basis rounds to 0.0% but is still below basis.
    sentence = fails_10pct_sentence(13.20, 13.21, 10.0, -0.04, 14.53)
    assert "0.0% below" in sentence
    assert "-0.0" not in sentence


@pytest.mark.unit
def test_sentence_legacy_negative_zero_pct_reads_below():
    # Legacy raw "strike -0.0% above basis" parses to -0.0 with no strike.
    sentence = fails_10pct_sentence(None, 100.0, 10.0, -0.0, 110.0)
    assert "0.0% below" in sentence
    assert "-0.0" not in sentence
