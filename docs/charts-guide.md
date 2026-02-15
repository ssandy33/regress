# Chart & Analysis Guide

This document explains each chart type in the Financial Regression Analysis Tool, what the visual elements mean, and how to interpret the accompanying statistics.

---

## 1. Linear Regression Chart

**Mode:** Linear

**What it shows:** A price-over-time trend line for a single asset. The chart fits a straight line through the asset's historical prices to reveal the overall direction and strength of the trend.

### Visual Elements

| Element | Description |
|---------|-------------|
| **Gray line (Actual)** | The asset's actual closing prices over the selected date range |
| **Blue line (Trend)** | The best-fit straight line through the price data |
| **Blue shaded band (95% CI)** | The 95% confidence interval around the trend line. If the trend is reliable, actual prices will mostly stay within this band |
| **Annotations** | User-added notes pinned to specific dates on the chart |

### Statistics

| Statistic | What it means |
|-----------|---------------|
| **R-Squared** | How much of the price variation is explained by the trend (0 to 1). Values above 0.7 indicate a strong trend; below 0.3 suggests no clear direction |
| **Slope** | The average price change per trading day. A positive slope means the asset is trending up; negative means down |
| **Intercept** | The modeled starting price at the beginning of the time series |
| **P-Value** | Statistical significance of the trend. Below 0.05 means the trend is statistically significant (unlikely due to chance). Displayed in green (significant), yellow (marginal), or red (not significant) |
| **Std Error** | The uncertainty in the slope estimate. Smaller values mean the slope is more precisely measured |

### Interpretation

The plain-English summary estimates an annualized return percentage (assuming ~252 trading days per year) and describes the trend strength. If the p-value is above 0.05, the summary warns that the apparent trend may be due to random price fluctuations rather than a real directional movement.

### When to use

- Determine whether an asset has been trending up or down over a period
- Estimate the rate of price appreciation or decline
- Check if a perceived trend is statistically real or just noise

---

## 2. Multi-Factor Regression Chart

**Mode:** Multi-Factor

**What it shows:** How well a combination of independent variables (factors) predicts a dependent variable. For example, you might model home prices as a function of interest rates, the S&P 500, and gold prices.

### Visual Elements

| Element | Description |
|---------|-------------|
| **Gray line (Actual)** | The actual values of the dependent variable |
| **Blue line (Predicted)** | The model's predicted values based on the selected factors |

The closer the blue line tracks the gray line, the better the model explains the dependent variable.

### Residual Chart

Displayed below the main chart when residuals are available.

| Element | Description |
|---------|-------------|
| **Green bars** | Dates where the actual value was higher than predicted (positive residual) |
| **Red bars** | Dates where the actual value was lower than predicted (negative residual) |

A good model shows small residuals scattered randomly. Large or clustered residuals suggest the model is missing important factors.

### Statistics

| Statistic | What it means |
|-----------|---------------|
| **R-Squared** | Proportion of dependent variable variance explained by all factors combined (0 to 1) |
| **Adjusted R-Squared** | R-Squared adjusted for the number of factors. Penalizes adding factors that don't improve the model. Always compare this to R-Squared; a large gap means some factors aren't contributing |
| **F-Statistic** | Tests whether the model as a whole is significant. Higher values indicate stronger overall explanatory power |
| **Intercept** | The predicted value of the dependent variable when all factors are zero |

### Coefficients Table

Each factor gets a row showing:

| Column | What it means |
|--------|---------------|
| **Coefficient** | How much the dependent variable changes per unit change in this factor, holding other factors constant |
| **P-Value** | Whether this factor's effect is statistically significant |
| **Significance** | Green "Significant" (p < 0.05), yellow "Marginal" (p < 0.10), or red "Not Significant" (p >= 0.10) |

### Alignment Notes

When factors have different data frequencies (e.g., daily stock prices and monthly economic data), the tool automatically resamples everything to the lowest common frequency. A blue info banner explains what alignment was performed.

### When to use

- Test whether economic indicators (interest rates, GDP, etc.) explain an asset's price movements
- Identify which factors have the strongest relationship with your target variable
- Build a simple predictive model for financial variables

---

## 3. Rolling Regression Chart

**Mode:** Rolling

**What it shows:** How the price trend changes over time by computing a linear regression within a sliding window that moves across the data. This reveals when trends strengthen, weaken, or reverse.

### Visual Elements

#### Top Panel: Price Chart

| Element | Description |
|---------|-------------|
| **Line with colored markers** | The asset's actual prices. Marker colors indicate trend strength at each point |
| **Green markers** | R-Squared >= 0.7 (strong trend) |
| **Yellow markers** | R-Squared 0.4 to 0.7 (moderate trend) |
| **Red markers** | R-Squared < 0.4 (weak or no trend) |

#### Bottom Panel: Rolling Metrics (Dual Y-Axis)

| Element | Description |
|---------|-------------|
| **Blue line (Slope, left axis)** | The slope of the trend within each window. Positive = prices rising; negative = falling. The magnitude indicates how quickly prices are changing |
| **Yellow line (R-Squared, right axis)** | The strength of the trend within each window (0 to 1). When this drops, the trend is breaking down |
| **Red "Trend break" annotations** | Automatically placed where R-Squared drops below 0.5 after being above it, signaling the end of a coherent trend |

### Statistics

| Statistic | What it means |
|-----------|---------------|
| **Current Slope** | The slope from the most recent window |
| **Current R-Squared** | The R-Squared from the most recent window |
| **Avg Slope** | Average slope across all windows |
| **Avg R-Squared** | Average R-Squared across all windows |
| **Min/Max Slope** | The range of slope values observed, showing the extremes of price movement |
| **Min/Max R-Squared** | The range of trend strength, from weakest to strongest |

### Window Size

The slider in the sidebar controls how many data points are in each window (default: 30 trading days). Smaller windows are more responsive to recent changes but noisier; larger windows are smoother but slower to react.

### When to use

- Detect when a trend started or ended
- Find periods of high volatility or directionless trading (low R-Squared)
- Compare the current trend strength to historical norms for the asset
- Identify trend reversals before they become obvious on a price chart

---

## 4. Comparison Chart

**Mode:** Compare

**What it shows:** Two to five assets normalized to a common base of 100, allowing direct visual comparison of relative performance regardless of price levels.

### Visual Elements

| Element | Description |
|---------|-------------|
| **Color-coded lines** | Each asset is assigned a distinct color. All start at 100 on the first date. A line at 120 means that asset is up 20% from the start; at 80 means down 20% |
| **Y-Axis (Normalized Value)** | Base 100 scale. The distance from 100 shows cumulative percentage gain or loss |
| **Annotations** | User-added notes pinned to specific dates |

### Statistics Table

Each asset gets a row showing:

| Column | What it means |
|--------|---------------|
| **Ann. Return** | Annualized return over the selected period. Green for positive, red for negative |
| **Volatility** | Annualized standard deviation of returns. Higher values mean more price swings. Useful for comparing risk across assets |
| **Trend R-Squared** | How consistently the asset moved in one direction (0 to 1). High R-Squared means a steady trend; low means choppy or directionless |

### When to use

- Compare performance of assets at different price levels (e.g., a $10 stock vs. a $3,000 index)
- Evaluate risk-adjusted returns across asset classes (stocks vs. bonds vs. commodities)
- Identify which assets moved together or diverged over a period
- Build a visual case for portfolio allocation decisions

---

## Common Features Across All Charts

### Data Quality Badge

Displayed above each chart showing:
- **Source** (yfinance, FRED, Zillow) — where the data came from
- **Frequency** (daily, monthly, quarterly) — the granularity of the data
- **Freshness indicator** — green dot for fresh data, yellow for stale (cached) data
- **Fetched date** — when the data was last retrieved from the source

### Stale Data Banner

A yellow warning banner appears when the app is serving cached data because the live data source was unavailable. The analysis still runs, but results may not reflect the most recent prices.

### Annotations

Available in Linear and Compare modes. Click "Add Annotation" to pin a text note to a specific date on the chart. Useful for marking events (earnings, rate changes, etc.) that may explain price movements.

### Export Options

- **CSV** — Download the underlying data as a spreadsheet-compatible file
- **Chart Image** — Use the Plotly toolbar (camera icon) to save the chart as a PNG

### Dark Mode

All charts automatically adapt to the selected theme. Toggle the sun/moon icon in the header to switch.
