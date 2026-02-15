import numpy as np
from scipy import stats
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.stattools import durbin_watson as compute_dw
from statsmodels.stats.outliers_influence import variance_inflation_factor

from app.utils.transforms import make_time_index


def compute_linear_regression(
    dates: list[str], values: list[float]
) -> dict:
    """Compute linear regression of values against a time index.

    Returns trend analysis: slope, intercept, r_squared, predicted values,
    and 95% confidence intervals.
    """
    n = len(values)
    if n < 3:
        raise ValueError("Need at least 3 data points for linear regression")

    t = make_time_index(n)
    y = np.array(values, dtype=float)

    result = stats.linregress(t, y)
    slope = float(result.slope)
    intercept = float(result.intercept)
    r_squared = float(result.rvalue ** 2)
    p_value = float(result.pvalue)
    std_error = float(result.stderr)

    predicted = slope * t + intercept
    residuals = y - predicted
    dw_value = float(compute_dw(residuals))

    # 95% confidence interval
    t_critical = stats.t.ppf(0.975, df=n - 2)
    # Standard error of prediction at each point
    t_mean = t.mean()
    se_pred = std_error * np.sqrt(1.0 / n + (t - t_mean) ** 2 / np.sum((t - t_mean) ** 2))
    margin = t_critical * se_pred

    return {
        "dates": dates,
        "actual_values": [float(v) for v in y],
        "predicted_values": [float(v) for v in predicted],
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "p_value": p_value,
        "confidence_interval_upper": [float(v) for v in (predicted + margin)],
        "confidence_interval_lower": [float(v) for v in (predicted - margin)],
        "std_error": std_error,
        "durbin_watson": dw_value,
        "sample_size": n,
    }


def compute_multifactor_ols(
    dates: list[str],
    y: list[float],
    x_df_dict: dict[str, list[float]],
) -> dict:
    """Run multi-factor OLS regression using statsmodels.

    y: dependent variable values
    x_df_dict: {factor_name: [values]} for independent variables

    Includes statistical safeguards:
    - ADF stationarity test on each series
    - Durbin-Watson autocorrelation test on residuals
    - VIF multicollinearity check per variable
    - Automatic differenced regression when non-stationarity detected
    """
    import pandas as pd

    y_arr = np.array(y, dtype=float)
    x_df = pd.DataFrame(x_df_dict)

    if len(y_arr) < len(x_df.columns) + 2:
        raise ValueError(
            f"Need at least {len(x_df.columns) + 2} observations for "
            f"{len(x_df.columns)} factors"
        )

    # --- ADF stationarity test on each input series ---
    stationarity = {}
    any_non_stationary = False

    for name in x_df.columns:
        adf_result = adfuller(x_df[name].values, autolag="AIC")
        is_stationary = adf_result[1] <= 0.05
        stationarity[name] = {
            "adf_statistic": float(adf_result[0]),
            "p_value": float(adf_result[1]),
            "is_stationary": is_stationary,
        }
        if not is_stationary:
            any_non_stationary = True

    # Test dependent variable
    adf_y = adfuller(y_arr, autolag="AIC")
    dep_stationary = adf_y[1] <= 0.05
    stationarity["__dependent__"] = {
        "adf_statistic": float(adf_y[0]),
        "p_value": float(adf_y[1]),
        "is_stationary": dep_stationary,
    }
    if not dep_stationary:
        any_non_stationary = True

    # --- Levels regression ---
    x_with_const = sm.add_constant(x_df)
    model = sm.OLS(y_arr, x_with_const).fit()

    coef_names = list(x_df.columns)
    coefficients = {name: float(model.params[name]) for name in coef_names}
    p_values = {name: float(model.pvalues[name]) for name in coef_names}

    # Durbin-Watson on levels residuals
    dw_value = float(compute_dw(model.resid))

    # VIF per variable
    vif_values = {}
    x_const_arr = x_with_const.values
    for i, name in enumerate(coef_names):
        col_idx = i + 1  # +1 to skip constant column
        vif_values[name] = float(variance_inflation_factor(x_const_arr, col_idx))

    result = {
        "dates": dates,
        "dependent_values": [float(v) for v in y_arr],
        "predicted_values": [float(v) for v in model.fittedvalues],
        "coefficients": coefficients,
        "intercept": float(model.params["const"]),
        "r_squared": float(model.rsquared),
        "adjusted_r_squared": float(model.rsquared_adj),
        "p_values": p_values,
        "f_statistic": float(model.fvalue),
        "residuals": [float(v) for v in model.resid],
        "durbin_watson": dw_value,
        "vif": vif_values,
        "stationarity": stationarity,
        "sample_size": len(y_arr),
    }

    # --- Differenced regression (when non-stationarity detected) ---
    if any_non_stationary and len(y_arr) > len(x_df.columns) + 3:
        y_diff = np.diff(y_arr)
        x_diff_df = x_df.diff().iloc[1:]  # drop first NaN row
        dates_diff = dates[1:]

        x_diff_const = sm.add_constant(x_diff_df)
        model_diff = sm.OLS(y_diff, x_diff_const).fit()

        diff_coef_names = list(x_diff_df.columns)
        result["differenced"] = {
            "dates": dates_diff,
            "dependent_values": [float(v) for v in y_diff],
            "predicted_values": [float(v) for v in model_diff.fittedvalues],
            "coefficients": {
                name: float(model_diff.params[name]) for name in diff_coef_names
            },
            "intercept": float(model_diff.params["const"]),
            "r_squared": float(model_diff.rsquared),
            "adjusted_r_squared": float(model_diff.rsquared_adj),
            "p_values": {
                name: float(model_diff.pvalues[name]) for name in diff_coef_names
            },
            "f_statistic": float(model_diff.fvalue),
            "residuals": [float(v) for v in model_diff.resid],
            "durbin_watson": float(compute_dw(model_diff.resid)),
        }

    return result


def compute_rolling_regression(
    dates: list[str], values: list[float], window_size: int
) -> dict:
    """Compute rolling linear regression of values against time index.

    For each window position, fits a linear regression of price vs time index
    and records the slope and R-squared.
    """
    n = len(values)
    if n < window_size:
        raise ValueError(
            f"Need at least {window_size} data points for rolling regression "
            f"with window size {window_size}, got {n}"
        )

    if window_size < 3:
        raise ValueError("Window size must be at least 3")

    y = np.array(values, dtype=float)
    slopes = []
    r_squareds = []

    for i in range(n - window_size + 1):
        window_y = y[i : i + window_size]
        window_t = make_time_index(window_size)

        # Use numpy lstsq for speed
        A = np.column_stack([window_t, np.ones(window_size)])
        result, residuals, _, _ = np.linalg.lstsq(A, window_y, rcond=None)
        slope = float(result[0])

        # Compute R-squared
        predicted = A @ result
        ss_res = np.sum((window_y - predicted) ** 2)
        ss_tot = np.sum((window_y - window_y.mean()) ** 2)
        r_sq = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        slopes.append(slope)
        r_squareds.append(r_sq)

    # Output dates correspond to the end of each window
    output_dates = dates[window_size - 1 :]

    return {
        "dates": output_dates,
        "slope_over_time": slopes,
        "r_squared_over_time": r_squareds,
        "actual_values": [float(v) for v in y],
    }
