**Subject: Financial Regression Analysis Tool — Quick Demo**

Hey Forrest, David,

I've been building a financial regression analysis tool and wanted to share a quick overview. It's a full-stack app that pulls data from Yahoo Finance, FRED, and Zillow, then runs different types of regression analysis with interactive charts.

### What it does

- **Linear Regression** — Fits a trend line to any asset's price history with confidence intervals and statistical significance testing
- **Multi-Factor Regression** — Models one asset as a function of others (e.g., "do interest rates and gold predict home prices?")
- **Rolling Regression** — Shows how trends strengthen and weaken over time with auto-detected trend breaks
- **Comparison Mode** — Normalizes 2-5 assets to base 100 for side-by-side performance comparison

It also includes session saving, data caching, dark mode, CSV export, and plain-English stat summaries so you don't have to interpret p-values manually.

### What strong vs. weak correlation looks like

**Strong correlation example — S&P 500 (^GSPC), 5-year linear trend:**
The S&P 500 over a multi-year bull run typically shows R-squared above 0.7, meaning 70%+ of price movement follows a steady upward trend. The trend line fits tightly, the confidence band is narrow, and the p-value is well below 0.05 (statistically significant). The interpretation panel would say something like "appreciated at approximately X% annually with a strong and statistically significant trend."

**Weak correlation example — Gold (GC=F), 3-year linear trend:**
Gold over a shorter or choppier period often shows R-squared below 0.3, meaning the straight-line trend explains very little of the price movement. The confidence band is wide, price whips above and below the trend line, and the p-value may be above 0.05 (not significant). The tool flags this: "the apparent trend may be due to random fluctuations rather than a real directional movement."

The rolling regression mode makes this even more visible — you can watch R-squared drop from green (strong) to red (weak) as trends break down, with automatic "trend break" annotations marking the exact dates.

### Tech stack

Python/FastAPI backend, React frontend, Plotly.js charts, SQLite caching. Runs locally via Docker or dev servers.

Happy to walk you through it or set up a time to demo. There's also a built-in help page that explains each chart type and what all the statistics mean.

Best,
Shawn
