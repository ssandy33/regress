"""Tests for app.utils.parsing — to_float() and to_int() coercion utilities."""

import pytest

from app.utils.parsing import to_float, to_int


class TestToFloat:
    """Tests for null-safe float coercion."""

    def test_valid_string(self):
        assert to_float("3.14") == 3.14

    def test_integer_string(self):
        assert to_float("42") == 42.0

    def test_none_input(self):
        assert to_float(None) == 0.0

    def test_empty_string(self):
        assert to_float("") == 0.0

    def test_non_numeric(self):
        assert to_float("abc") == 0.0

    def test_custom_default(self):
        assert to_float("abc", default=None) is None

    def test_custom_default_numeric(self):
        assert to_float(None, default=-1.0) == -1.0

    def test_with_commas_returns_default(self):
        """Python's float() does not handle commas — returns default."""
        assert to_float("1,234.56") == 0.0

    def test_boolean_input(self):
        """Python float(True) == 1.0, float(False) == 0.0."""
        assert to_float(True) == 1.0
        assert to_float(False) == 0.0

    def test_already_float(self):
        assert to_float(3.14) == 3.14

    def test_whitespace_string(self):
        """Python float() strips leading/trailing whitespace."""
        assert to_float("  3.14  ") == 3.14

    def test_negative_string(self):
        assert to_float("-7.5") == -7.5

    def test_scientific_notation(self):
        assert to_float("1e3") == 1000.0

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("0", 0.0),
            ("0.0", 0.0),
            ("-0", 0.0),
            ("inf", float("inf")),
            ("-inf", float("-inf")),
        ],
    )
    def test_edge_numeric_strings(self, value, expected):
        assert to_float(value) == expected


class TestToInt:
    """Tests for null-safe int coercion via int(float(value))."""

    def test_valid_string(self):
        assert to_int("42") == 42

    def test_none_input(self):
        assert to_int(None) == 0

    def test_empty_string(self):
        assert to_int("") == 0

    def test_float_string_truncates(self):
        """int(float('3.7')) truncates toward zero, not rounds."""
        assert to_int("3.7") == 3

    def test_negative_float_string_truncates_toward_zero(self):
        """int(float('-2.9')) == -2, not -3."""
        assert to_int("-2.9") == -2

    def test_non_numeric(self):
        assert to_int("abc") == 0

    def test_custom_default(self):
        assert to_int("abc", default=-1) == -1

    def test_already_int(self):
        assert to_int(42) == 42

    def test_float_input_truncates(self):
        assert to_int(3.9) == 3

    def test_zero(self):
        assert to_int("0") == 0

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("1", 1),
            ("100", 100),
            ("-5", -5),
            ("0.0", 0),
            ("9.99", 9),
        ],
    )
    def test_various_numeric_strings(self, value, expected):
        assert to_int(value) == expected
