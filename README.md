# Financial Regression Analysis Tool

A full-stack application for financial data analysis with linear, multi-factor, rolling, and comparison regression models. Fetches data from yfinance, FRED, and Zillow, caches it locally, and presents interactive Plotly charts with statistical summaries.

![Screenshot placeholder](docs/screenshot.png)

## Features

- **Linear Regression** — Price vs time trend with confidence intervals
- **Multi-Factor Regression** — OLS with automatic frequency alignment across data sources
- **Rolling Regression** — Sliding window trend analysis with auto-annotated trend breaks
- **Comparison Mode** — Normalize 2-5 assets to a common base for side-by-side analysis
- **Real Estate Analysis** — Case-Shiller metro indices and Zillow zip code data
- **Session Management** — Save, reload, and share analysis configurations
- **Chart Annotations** — Add custom notes to chart dates
- **Data Quality Indicators** — Source badges, staleness warnings, alignment notes
- **Plain-English Interpretation** — Auto-generated summaries of statistical results
- **Dark Mode** — Full dark/light theme support
- **Export** — CSV data export and Plotly chart image export

## Prerequisites

- **Docker** and **Docker Compose** (recommended), or:
  - Python 3.12+
  - Node.js 20+
- **FRED API Key** (free) — [Get one here](https://fred.stlouisfed.org/docs/api/api_key.html)
  - Required for interest rates, housing indices, and economic data
  - Stock/index data works without it via yfinance

## Quick Start (Docker)

```bash
# Clone the repository
git clone <repo-url> regression_tool
cd regression_tool

# Set up your FRED API key
cp backend/.env.example backend/.env
# Edit backend/.env and add your key

# Build and run
docker-compose up --build

# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API docs: http://localhost:8000/docs
```

## Development Setup (without Docker)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your FRED API key

# Run
uvicorn app.main:app --reload
# API available at http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# App available at http://localhost:3000
# Vite proxies /api/* to localhost:8000
```

### Running Tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

## Architecture

```
regression_tool/
├── backend/                    # Python/FastAPI
│   ├── app/
│   │   ├── main.py             # App entry, lifespan, CORS, error handlers
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── routers/            # API endpoints
│   │   │   ├── assets.py       # Asset search, Case-Shiller list, suggestions
│   │   │   ├── data.py         # Historical data (auto-detect source)
│   │   │   ├── regression.py   # Linear, multi-factor, rolling, compare
│   │   │   ├── sessions.py     # CRUD for saved sessions
│   │   │   └── settings.py     # App settings, cache management
│   │   ├── services/
│   │   │   ├── data_fetcher.py # yfinance/FRED/Zillow with cache + retry
│   │   │   ├── regression.py   # Regression computation engines
│   │   │   └── cache.py        # SQLite cache with freshness rules
│   │   ├── models/
│   │   │   ├── database.py     # SQLAlchemy models
│   │   │   └── schemas.py      # Pydantic request/response schemas
│   │   └── utils/
│   │       └── transforms.py   # Dataset alignment, frequency detection
│   └── tests/
├── frontend/                   # React + Vite
│   ├── src/
│   │   ├── api/client.js       # Axios API wrapper
│   │   ├── components/
│   │   │   ├── layout/         # Header, Sidebar, Layout, LoadingSkeleton
│   │   │   ├── controls/       # AssetSelector, DateRangePicker, ComparePicker, etc.
│   │   │   ├── charts/         # Plotly charts for each regression mode
│   │   │   ├── results/        # StatsPanel, Interpretation, Annotations, Export
│   │   │   ├── sessions/       # Save/load sessions
│   │   │   └── settings/       # Settings page, Setup wizard
│   │   ├── hooks/              # useRegression, useAssetSearch, useSessions
│   │   ├── context/            # ThemeContext (dark/light mode)
│   │   └── utils/              # Formatters, CSV export
│   └── nginx.conf              # Production SPA + API proxy config
└── docker-compose.yml
```

## API Documentation

When the backend is running, interactive API docs are available at:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/assets/search?q=` | Search assets |
| GET | `/api/data/{ticker}` | Historical data |
| POST | `/api/regression/linear` | Linear regression |
| POST | `/api/regression/multi-factor` | Multi-factor OLS |
| POST | `/api/regression/rolling` | Rolling regression |
| POST | `/api/regression/compare` | Compare assets |
| GET | `/api/settings` | App settings |

## Tech Stack

**Backend**: Python 3.12, FastAPI, SQLAlchemy, SQLite, yfinance, fredapi, statsmodels, scipy, pandas, tenacity

**Frontend**: React 18, Vite, Tailwind CSS, Plotly.js, Axios, React Router, react-datepicker, react-hot-toast

**Infrastructure**: Docker, nginx, Docker Compose

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`pytest tests/ -v`)
5. Commit and push
6. Open a Pull Request
