from datetime import datetime

import numpy as np
import pandas as pd


def align_datasets(datasets: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[str]]:
    """Align multiple time series to a common frequency and date range.

    Each input DataFrame must have a DatetimeIndex and a single 'value' column.
    Returns the aligned DataFrame and a list of alignment notes.
    """
    notes: list[str] = []

    if not datasets:
        raise ValueError("No datasets provided for alignment")

    # Determine frequencies
    freq_order = {"daily": 0, "monthly": 1, "quarterly": 2}
    frequencies = {}
    for name, df in datasets.items():
        inferred = _infer_frequency(df)
        frequencies[name] = inferred

    unique_freqs = set(frequencies.values())
    target_freq = max(unique_freqs, key=lambda f: freq_order.get(f, 0))

    if len(unique_freqs) > 1:
        notes.append(
            f"Resampled all series to {target_freq} frequency "
            f"(mixed frequencies: {', '.join(f'{k}={v}' for k, v in frequencies.items())})"
        )

    # Resample to target frequency
    freq_map = {"daily": "D", "monthly": "ME", "quarterly": "QE"}
    target_pd_freq = freq_map[target_freq]

    resampled = {}
    for name, df in datasets.items():
        if frequencies[name] != target_freq:
            series = df["value"].resample(target_pd_freq).last()
        else:
            series = df["value"]
        resampled[name] = series

    # Combine with inner join
    combined = pd.DataFrame(resampled)

    # Forward-fill gaps (limit 5)
    combined = combined.ffill(limit=5)

    # Drop remaining NaNs
    rows_before = len(combined)
    combined = combined.dropna()
    rows_dropped = rows_before - len(combined)

    if rows_dropped > 0:
        notes.append(f"Dropped {rows_dropped} rows with missing values after alignment")

    notes.append(f"Aligned dataset: {len(combined)} observations from {combined.index[0].date()} to {combined.index[-1].date()}")

    return combined, notes


def _infer_frequency(df: pd.DataFrame) -> str:
    """Infer frequency from a DataFrame's DatetimeIndex."""
    if len(df) < 2:
        return "daily"

    diffs = pd.Series(df.index).diff().dropna()
    median_days = diffs.dt.days.median()

    if median_days <= 7:
        return "daily"
    elif median_days <= 45:
        return "monthly"
    else:
        return "quarterly"


def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def make_time_index(n: int) -> np.ndarray:
    """Create a numeric time index array [0, 1, 2, ..., n-1]."""
    return np.arange(n, dtype=float)
