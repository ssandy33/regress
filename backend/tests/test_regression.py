import pytest
import numpy as np

from app.services.regression import (
    compute_linear_regression,
    compute_multifactor_ols,
    compute_rolling_regression,
)


class TestLinearRegression:
    def test_perfect_linear_trend(self):
        """y = 2t + 1 should give slope ~2, intercept ~1, r_squared ~1."""
        dates = [f"2024-01-{i+1:02d}" for i in range(50)]
        values = [2 * t + 1 for t in range(50)]

        result = compute_linear_regression(dates, values)

        assert result["slope"] == pytest.approx(2.0, abs=1e-10)
        assert result["intercept"] == pytest.approx(1.0, abs=1e-10)
        assert result["r_squared"] == pytest.approx(1.0, abs=1e-10)
        assert result["p_value"] < 0.001
        assert len(result["dates"]) == 50
        assert len(result["predicted_values"]) == 50
        assert len(result["confidence_interval_upper"]) == 50
        assert len(result["confidence_interval_lower"]) == 50

    def test_noisy_linear_trend(self):
        """Noisy data should still find approximate trend."""
        np.random.seed(42)
        n = 100
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        values = [3 * t + 10 + np.random.normal(0, 5) for t in range(n)]

        result = compute_linear_regression(dates, values)

        assert result["slope"] == pytest.approx(3.0, abs=0.5)
        assert result["intercept"] == pytest.approx(10.0, abs=5.0)
        assert result["r_squared"] > 0.9

    def test_too_few_points_raises(self):
        """Need at least 3 data points."""
        with pytest.raises(ValueError, match="at least 3"):
            compute_linear_regression(["2024-01-01", "2024-01-02"], [1.0, 2.0])

    def test_confidence_intervals_bracket_predictions(self):
        """Upper CI should be above predicted, lower should be below."""
        dates = [f"2024-01-{i+1:02d}" for i in range(20)]
        values = [float(i * 2 + 5) for i in range(20)]

        result = compute_linear_regression(dates, values)

        for i in range(len(result["predicted_values"])):
            assert result["confidence_interval_upper"][i] >= result["predicted_values"][i]
            assert result["confidence_interval_lower"][i] <= result["predicted_values"][i]


class TestMultiFactorOLS:
    def test_known_coefficients(self):
        """y = 2*x1 + 3*x2 + 5 should recover coefficients."""
        np.random.seed(42)
        n = 100
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        x1 = np.random.randn(n) * 10
        x2 = np.random.randn(n) * 5

        y = (2 * x1 + 3 * x2 + 5).tolist()

        result = compute_multifactor_ols(
            dates, y, {"x1": x1.tolist(), "x2": x2.tolist()}
        )

        assert result["coefficients"]["x1"] == pytest.approx(2.0, abs=1e-10)
        assert result["coefficients"]["x2"] == pytest.approx(3.0, abs=1e-10)
        assert result["intercept"] == pytest.approx(5.0, abs=1e-10)
        assert result["r_squared"] == pytest.approx(1.0, abs=1e-10)
        assert len(result["residuals"]) == n
        assert len(result["predicted_values"]) == n

    def test_noisy_coefficients(self):
        """With noise, should still approximately recover coefficients."""
        np.random.seed(42)
        n = 200
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        x1 = np.random.randn(n) * 10
        x2 = np.random.randn(n) * 5
        noise = np.random.randn(n) * 2

        y = (2 * x1 + 3 * x2 + 5 + noise).tolist()

        result = compute_multifactor_ols(
            dates, y, {"x1": x1.tolist(), "x2": x2.tolist()}
        )

        assert result["coefficients"]["x1"] == pytest.approx(2.0, abs=0.5)
        assert result["coefficients"]["x2"] == pytest.approx(3.0, abs=0.5)
        assert result["r_squared"] > 0.9

    def test_insufficient_observations_raises(self):
        """Should raise if fewer observations than factors + 2."""
        with pytest.raises(ValueError, match="observations"):
            compute_multifactor_ols(
                ["2024-01-01", "2024-01-02"],
                [1.0, 2.0],
                {"x1": [1.0, 2.0], "x2": [3.0, 4.0]},
            )


class TestRollingRegression:
    def test_output_length(self):
        """Output length should be n - window + 1."""
        n = 50
        window = 10
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        values = [float(i) for i in range(n)]

        result = compute_rolling_regression(dates, values, window)

        assert len(result["dates"]) == n - window + 1
        assert len(result["slope_over_time"]) == n - window + 1
        assert len(result["r_squared_over_time"]) == n - window + 1
        assert len(result["actual_values"]) == n

    def test_constant_slope(self):
        """A perfect linear series should have constant slope across windows."""
        n = 30
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        values = [2.0 * i + 1.0 for i in range(n)]

        result = compute_rolling_regression(dates, values, window_size=10)

        for slope in result["slope_over_time"]:
            assert slope == pytest.approx(2.0, abs=1e-10)

        for r_sq in result["r_squared_over_time"]:
            assert r_sq == pytest.approx(1.0, abs=1e-10)

    def test_insufficient_data_raises(self):
        """Should raise if fewer data points than window size."""
        with pytest.raises(ValueError, match="at least"):
            compute_rolling_regression(
                ["2024-01-01", "2024-01-02", "2024-01-03"],
                [1.0, 2.0, 3.0],
                window_size=5,
            )

    def test_window_too_small_raises(self):
        """Window size must be at least 3."""
        with pytest.raises(ValueError, match="at least 3"):
            compute_rolling_regression(
                ["2024-01-01", "2024-01-02", "2024-01-03"],
                [1.0, 2.0, 3.0],
                window_size=2,
            )


class TestStatisticalSafeguards:
    """Tests for Phase 4 statistical safeguards: DW, VIF, ADF, differenced regression."""

    def test_multifactor_returns_durbin_watson(self):
        """Durbin-Watson should be in valid range [0, 4]."""
        np.random.seed(42)
        n = 100
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        x1 = np.random.randn(n) * 10
        x2 = np.random.randn(n) * 5
        y = (2 * x1 + 3 * x2 + 5 + np.random.randn(n)).tolist()

        result = compute_multifactor_ols(dates, y, {"x1": x1.tolist(), "x2": x2.tolist()})

        assert "durbin_watson" in result
        assert 0 <= result["durbin_watson"] <= 4

    def test_multifactor_returns_vif(self):
        """Uncorrelated variables should have low VIF (< 5)."""
        np.random.seed(42)
        n = 100
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        x1 = np.random.randn(n) * 10
        x2 = np.random.randn(n) * 5  # uncorrelated with x1
        y = (2 * x1 + 3 * x2 + 5 + np.random.randn(n)).tolist()

        result = compute_multifactor_ols(dates, y, {"x1": x1.tolist(), "x2": x2.tolist()})

        assert "vif" in result
        assert "x1" in result["vif"]
        assert "x2" in result["vif"]
        assert result["vif"]["x1"] < 5
        assert result["vif"]["x2"] < 5

    def test_multifactor_stationarity_on_random_walk(self):
        """Random walk (cumulative sum) should be detected as non-stationary, triggering differenced regression."""
        np.random.seed(42)
        n = 200
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        # Random walks are non-stationary
        x1 = np.cumsum(np.random.randn(n)).tolist()
        x2 = np.cumsum(np.random.randn(n)).tolist()
        y = np.cumsum(np.random.randn(n)).tolist()

        result = compute_multifactor_ols(dates, y, {"x1": x1, "x2": x2})

        assert "stationarity" in result
        # At least one series should be detected as non-stationary
        has_non_stationary = any(
            not v["is_stationary"] for v in result["stationarity"].values()
        )
        assert has_non_stationary
        # Differenced regression should be present
        assert "differenced" in result
        assert "r_squared" in result["differenced"]
        assert "durbin_watson" in result["differenced"]

    def test_multifactor_stationary_series(self):
        """Stationary white noise should be detected as stationary with no differenced key."""
        np.random.seed(42)
        n = 200
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        x1 = np.random.randn(n).tolist()
        x2 = np.random.randn(n).tolist()
        y = (np.array(x1) * 2 + np.array(x2) * 3 + np.random.randn(n) * 0.5).tolist()

        result = compute_multifactor_ols(dates, y, {"x1": x1, "x2": x2})

        assert "stationarity" in result
        # All series should be stationary
        all_stationary = all(
            v["is_stationary"] for v in result["stationarity"].values()
        )
        assert all_stationary
        # No differenced regression needed
        assert "differenced" not in result

    def test_linear_returns_durbin_watson(self):
        """Linear regression should include Durbin-Watson statistic."""
        np.random.seed(42)
        n = 50
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        values = [float(i * 2 + 5 + np.random.randn()) for i in range(n)]

        result = compute_linear_regression(dates, values)

        assert "durbin_watson" in result
        assert 0 <= result["durbin_watson"] <= 4

    def test_sample_size_returned(self):
        """Both linear and multi-factor should return sample_size matching input length."""
        np.random.seed(42)
        n = 75
        dates = [f"2024-01-{i+1:02d}" for i in range(n)]
        values = [float(i + np.random.randn()) for i in range(n)]

        linear_result = compute_linear_regression(dates, values)
        assert linear_result["sample_size"] == n

        x1 = np.random.randn(n).tolist()
        multi_result = compute_multifactor_ols(dates, values, {"x1": x1})
        assert multi_result["sample_size"] == n
