"""Unit tests for :mod:`app.services.rejection_messages`.

Each rejection code emitted by :class:`OptionScanner` has one test that asserts
the human sentence contains the key parameters and reads like a sentence (not
a code dump). The mapper is a pure function so these tests do not need any
fixtures from ``conftest.py``.

Spec: ``frontend/design-specs/scanner-education-v0.5.7.md`` §5.3.
"""

import pytest

from app.services.rejection_messages import HumanizeContext, humanize_reasons


# -- Per-code tests ---------------------------------------------------------


class TestFails10PctRule:
    """``fails_10pct_rule`` — strike is too close to or below cost basis."""

    @pytest.mark.unit
    def test_with_cost_basis_in_context(self):
        raw = ["fails_10pct_rule: strike 645.7% above basis, requires 10.0%"]
        ctx: HumanizeContext = {"cost_basis": 13.26}
        out = humanize_reasons(raw, ctx)
        assert len(out) == 1
        sentence = out[0]
        assert "645.7%" in sentence
        assert "$13.26 basis" in sentence
        assert "10.0% rule requires" in sentence

    @pytest.mark.unit
    def test_without_cost_basis_in_context(self):
        raw = ["fails_10pct_rule: strike 5.0% above basis, requires 10.0%"]
        out = humanize_reasons(raw, context=None)
        assert out[0].startswith("Strike sits 5.0%")
        assert "your cost basis" in out[0]
        assert "10.0% rule" in out[0]


class TestItmPut:
    """``itm_put`` — put strike sits above the current price."""

    @pytest.mark.unit
    def test_basic(self):
        raw = ["itm_put: strike $15.00 > price $14.00"]
        out = humanize_reasons(raw, None)
        assert out[0].startswith("Strike $15.00")
        assert "$14.00" in out[0]
        assert "in-the-money" in out[0]


class TestDeltaOutOfRange:
    """``delta_out_of_range`` has two distinct sub-cases (too high vs too low)."""

    @pytest.mark.unit
    def test_too_high_explanation(self):
        # |0.42| > max_delta 0.35
        raw = ["delta_out_of_range: |0.42| not in [0.15, 0.35]"]
        out = humanize_reasons(raw, None)
        sentence = out[0]
        assert "+0.42" in sentence
        assert "0.15" in sentence and "0.35" in sentence
        assert "too close to the money" in sentence
        # Sub-case sanity: the "too far OTM" clause must NOT appear here.
        assert "too far out of the money" not in sentence

    @pytest.mark.unit
    def test_too_low_explanation(self):
        # |0.05| < min_delta 0.15
        raw = ["delta_out_of_range: |0.05| not in [0.15, 0.35]"]
        out = humanize_reasons(raw, None)
        sentence = out[0]
        assert "+0.05" in sentence
        assert "too far out of the money" in sentence
        # Sub-case sanity: the "too close" clause must NOT appear here.
        assert "too close to the money" not in sentence

    @pytest.mark.unit
    def test_negative_delta_for_csp(self):
        # Puts have negative delta; sign should be preserved in the sentence.
        raw = ["delta_out_of_range: |-0.42| not in [0.15, 0.35]"]
        out = humanize_reasons(raw, None)
        sentence = out[0]
        assert "-0.42" in sentence
        assert "too close to the money" in sentence


class TestLowOpenInterest:
    """``low_open_interest`` — strike below the OI threshold."""

    @pytest.mark.unit
    def test_basic(self):
        raw = ["low_open_interest: 12 < 50"]
        out = humanize_reasons(raw, None)
        assert out[0].startswith("Only 12 contracts")
        assert "at least 50" in out[0]


class TestZeroBid:
    """``zero_bid`` — no bid in the market."""

    @pytest.mark.unit
    def test_basic(self):
        out = humanize_reasons(["zero_bid"], None)
        assert "No buyer" in out[0]
        assert "bid" in out[0]


class TestReturnBelowTarget:
    """``return_below_target`` — premium yield under user threshold."""

    @pytest.mark.unit
    def test_basic(self):
        raw = ["return_below_target: 0.34% < 1.0%"]
        out = humanize_reasons(raw, None)
        sentence = out[0]
        assert "0.34%" in sentence
        assert "1.0% target" in sentence


class TestReturnAboveCap:
    """``return_above_cap`` — premium yield above user sanity cap."""

    @pytest.mark.unit
    def test_basic(self):
        raw = ["return_above_cap: 25.50% > 15.0%"]
        out = humanize_reasons(raw, None)
        sentence = out[0]
        assert "25.50%" in sentence
        assert "15.0% cap" in sentence
        assert "too close to the money" in sentence


# -- Mapper-wide guarantees -------------------------------------------------


class TestUnknownCodeFallback:
    """Unknown codes pass through unchanged — never crash, never lose info."""

    @pytest.mark.unit
    def test_unknown_code_returns_raw(self):
        out = humanize_reasons(["some_future_rule_we_have_not_mapped"], None)
        assert out == ["some_future_rule_we_have_not_mapped"]

    @pytest.mark.unit
    def test_malformed_known_code_returns_raw(self):
        # The prefix matches but the body doesn't fit the regex — fall through.
        raw_str = "fails_10pct_rule: some garbled message"
        out = humanize_reasons([raw_str], None)
        assert out == [raw_str]


class TestMapperShape:
    """Length and order invariants — the output list mirrors the input list."""

    @pytest.mark.unit
    def test_empty_input_returns_empty(self):
        assert humanize_reasons([], None) == []

    @pytest.mark.unit
    def test_multiple_reasons_preserve_order(self):
        raw = [
            "fails_10pct_rule: strike 5.0% above basis, requires 10.0%",
            "zero_bid",
            "low_open_interest: 12 < 50",
        ]
        out = humanize_reasons(raw, {"cost_basis": 13.26})
        assert len(out) == 3
        assert out[0].startswith("Strike sits 5.0%")
        assert out[1].startswith("No buyer")
        assert out[2].startswith("Only 12 contracts")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "raw",
        [
            "fails_10pct_rule: strike 5.0% above basis, requires 10.0%",
            "itm_put: strike $15.00 > price $14.00",
            "delta_out_of_range: |0.42| not in [0.15, 0.35]",
            "low_open_interest: 12 < 50",
            "zero_bid",
            "return_below_target: 0.34% < 1.0%",
            "return_above_cap: 25.50% > 15.0%",
        ],
    )
    def test_all_known_codes_produce_non_raw_output(self, raw):
        """Smoke check: each known code maps to something different from raw."""
        out = humanize_reasons([raw], {"cost_basis": 13.26})
        assert len(out) == 1
        assert out[0] != raw
        # Soft check: no code-shaped output (no ":<digits>%<more digits>" tail).
        assert ": " not in out[0] or "—" in out[0]
