"""Tests for app.utils.transforms — align_datasets, _infer_frequency, parse_date, make_time_index."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from app.utils.transforms import (
    _infer_frequency,
    align_datasets,
    make_time_index,
    parse_date,
)


def _make_df(start: str, periods: int, freq: str = "D", values: list[float] | None = None) -> pd.DataFrame:
    """Build a DataFrame with DatetimeIndex and a 'value' column."""
    dates = pd.date_range(start, periods=periods, freq=freq)
    if values is not None:
        data = values
    else:
        data = list(range(1, periods + 1))
    return pd.DataFrame({"value": [float(v) for v in data]}, index=dates)


class TestAlignDatasets:
    """Tests for align_datasets() — multi-series alignment to common frequency."""

    def test_align_two_datasets_matching_dates(self):
        """Two daily series with identical dates preserve all rows."""
        df_a = _make_df("2023-01-01", 30)
        df_b = _make_df("2023-01-01", 30)
        combined, notes = align_datasets({"A": df_a, "B": df_b})
        assert len(combined) == 30
        assert list(combined.columns) == ["A", "B"]
        assert not any("Dropped" in n for n in notes)

    def test_align_datasets_with_partial_overlap(self):
        """Two daily series with partial overlap — ffill extends beyond raw intersection.

        DataFrame constructor creates a union of indices. Series A ends Jan 31
        but gets forward-filled 5 rows into Feb (ffill limit=5), so the aligned
        range is Jan 15 - Feb 5 = 22 rows, not the raw 17-day overlap.
        """
        df_a = _make_df("2023-01-01", 31)  # Jan 1-31
        df_b = _make_df("2023-01-15", 31)  # Jan 15 - Feb 14
        combined, notes = align_datasets({"A": df_a, "B": df_b})
        # 17 overlap + 5 ffill = 22
        assert len(combined) == 22
        assert combined.index[0] == pd.Timestamp("2023-01-15")
        assert combined.index[-1] == pd.Timestamp("2023-02-05")

    def test_align_empty_dict_raises(self):
        """Empty input raises ValueError."""
        with pytest.raises(ValueError, match="No datasets provided"):
            align_datasets({})

    def test_align_single_dataset(self):
        """Single DataFrame returns one-column result with all rows."""
        df = _make_df("2023-01-01", 20)
        combined, notes = align_datasets({"only": df})
        assert len(combined) == 20
        assert list(combined.columns) == ["only"]

    def test_align_datasets_preserves_chronological_order(self):
        """Output index is monotonically increasing."""
        df_a = _make_df("2023-01-01", 30)
        df_b = _make_df("2023-01-05", 30)
        combined, _ = align_datasets({"A": df_a, "B": df_b})
        assert combined.index.is_monotonic_increasing

    def test_align_datasets_notes_contain_observation_count(self):
        """Notes include the 'Aligned dataset: N observations' string."""
        df_a = _make_df("2023-01-01", 10)
        df_b = _make_df("2023-01-01", 10)
        _, notes = align_datasets({"A": df_a, "B": df_b})
        assert any("Aligned dataset: 10 observations" in n for n in notes)

    def test_align_mixed_frequencies_resamples(self):
        """Daily + monthly series triggers resampling note."""
        df_daily = _make_df("2023-01-01", 90, freq="D")
        df_monthly = _make_df("2023-01-31", 3, freq="ME")
        combined, notes = align_datasets({"daily": df_daily, "monthly": df_monthly})
        assert any("Resampled" in n for n in notes)
        assert any("monthly" in n for n in notes)

    def test_align_datasets_ffill_limit(self):
        """Gaps beyond ffill limit=5 cause rows to be dropped."""
        # Create two series where one has a 7-day gap
        dates_a = pd.date_range("2023-01-01", periods=20, freq="D")
        df_a = pd.DataFrame({"value": range(20)}, index=dates_a, dtype=float)

        # Series B is missing days 5-12 (8-day gap)
        dates_b = list(pd.date_range("2023-01-01", periods=4, freq="D")) + \
                  list(pd.date_range("2023-01-13", periods=8, freq="D"))
        df_b = pd.DataFrame({"value": range(12)}, index=dates_b, dtype=float)

        combined, notes = align_datasets({"A": df_a, "B": df_b})
        assert any("Dropped" in n for n in notes)

    def test_align_datasets_empty_result_raises_index_error(self):
        """When alignment produces zero rows, accessing index[0] raises IndexError.

        This documents a known gap in align_datasets() — it does not guard
        against an empty result after dropna. All-NaN input series trigger this
        because ffill has nothing to propagate and dropna removes every row.
        """
        df_a = pd.DataFrame(
            {"value": [np.nan] * 3},
            index=pd.date_range("2023-01-01", periods=3, freq="D"),
        )
        df_b = pd.DataFrame(
            {"value": [np.nan] * 3},
            index=pd.date_range("2023-01-01", periods=3, freq="D"),
        )
        with pytest.raises(IndexError):
            align_datasets({"A": df_a, "B": df_b})

    def test_align_datasets_column_values_correct(self):
        """Aligned values match the original series values."""
        df_a = _make_df("2023-01-01", 5, values=[10.0, 20.0, 30.0, 40.0, 50.0])
        df_b = _make_df("2023-01-01", 5, values=[1.0, 2.0, 3.0, 4.0, 5.0])
        combined, _ = align_datasets({"A": df_a, "B": df_b})
        assert list(combined["A"]) == [10.0, 20.0, 30.0, 40.0, 50.0]
        assert list(combined["B"]) == [1.0, 2.0, 3.0, 4.0, 5.0]


class TestInferFrequency:
    """Tests for _infer_frequency() — median-gap frequency detection."""

    def test_daily_frequency(self):
        df = _make_df("2023-01-01", 30, freq="D")
        assert _infer_frequency(df) == "daily"

    def test_monthly_frequency(self):
        df = _make_df("2023-01-31", 6, freq="ME")
        assert _infer_frequency(df) == "monthly"

    def test_quarterly_frequency(self):
        df = _make_df("2023-03-31", 4, freq="QE")
        assert _infer_frequency(df) == "quarterly"

    def test_single_row_returns_daily(self):
        """A single-row DataFrame defaults to 'daily'."""
        df = _make_df("2023-01-01", 1)
        assert _infer_frequency(df) == "daily"

    def test_weekly_infers_as_daily(self):
        """Weekly data (median ~7 days) falls within the daily threshold (<=7)."""
        df = _make_df("2023-01-01", 10, freq="W")
        assert _infer_frequency(df) == "daily"


class TestParseDate:
    """Tests for parse_date() — YYYY-MM-DD string to datetime."""

    def test_valid_date(self):
        result = parse_date("2023-06-15")
        assert result == datetime(2023, 6, 15)

    def test_valid_date_type(self):
        result = parse_date("2023-01-01")
        assert isinstance(result, datetime)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_date("06/15/2023")

    def test_nonsense_string_raises(self):
        with pytest.raises(ValueError):
            parse_date("not-a-date")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_date("")

    def test_leap_day(self):
        result = parse_date("2024-02-29")
        assert result == datetime(2024, 2, 29)


class TestMakeTimeIndex:
    """Tests for make_time_index() — sequential float array generation."""

    def test_returns_correct_length(self):
        result = make_time_index(5)
        assert len(result) == 5

    def test_returns_float_dtype(self):
        result = make_time_index(3)
        assert result.dtype == float

    def test_values_are_sequential(self):
        result = make_time_index(4)
        np.testing.assert_array_equal(result, [0.0, 1.0, 2.0, 3.0])

    def test_zero_length(self):
        result = make_time_index(0)
        assert len(result) == 0
        assert result.dtype == float

    def test_single_element(self):
        result = make_time_index(1)
        np.testing.assert_array_equal(result, [0.0])

    def test_returns_numpy_array(self):
        result = make_time_index(3)
        assert isinstance(result, np.ndarray)
