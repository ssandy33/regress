# C4 Component Diagram — Regression Analysis Tool

## System Context (Level 1)

```mermaid
C4Context
    title System Context — Financial Regression Tool

    Person(user, "Analyst", "Runs regression analysis on financial & housing data")

    System(app, "Regression Analysis Tool", "Full-stack app for linear, multi-factor, rolling, and comparison regressions")

    System_Ext(yahoo, "Yahoo Finance", "Stock prices, indices, commodities, earnings dates")
    System_Ext(fred, "FRED API", "Interest rates, housing indices, economic indicators")
    System_Ext(zillow, "Zillow Research", "ZHVI home values by zip code (public CSV)")

    Rel(user, app, "Configures & runs analysis", "HTTPS")
    Rel(app, yahoo, "Fetches market data", "HTTPS")
    Rel(app, fred, "Fetches economic data", "HTTPS + API key")
    Rel(app, zillow, "Downloads CSV", "HTTPS")
```

## Container Diagram (Level 2)

```mermaid
C4Container
    title Container Diagram — Financial Regression Tool

    Person(user, "Analyst")

    System_Boundary(sys, "Regression Analysis Tool") {
        Container(frontend, "Frontend SPA", "React 19, Plotly, Tailwind CSS", "Analysis UI with charts, controls, and session management")
        Container(backend, "Backend API", "FastAPI, Python 3.12", "REST API for data fetching, regression, caching, sessions")
        ContainerDb(db, "SQLite Database", "SQLAlchemy", "Cache entries, sessions, app settings")
    }

    System_Ext(yahoo, "Yahoo Finance")
    System_Ext(fred, "FRED API")
    System_Ext(zillow, "Zillow Research")

    Rel(user, frontend, "Uses", "HTTPS")
    Rel(frontend, backend, "API calls", "HTTP/JSON")
    Rel(backend, db, "Reads/writes", "SQLAlchemy")
    Rel(backend, yahoo, "Market data", "HTTPS")
    Rel(backend, fred, "Economic data", "HTTPS")
    Rel(backend, zillow, "Housing CSV", "HTTPS")
```

## Component Diagram — Backend (Level 3)

```mermaid
C4Component
    title Component Diagram — Backend API

    Container_Boundary(api, "FastAPI Backend") {

        Component(reg_router, "Regression Router", "FastAPI Router", "POST /api/regression/{linear,multi-factor,rolling,compare}")
        Component(data_router, "Data Router", "FastAPI Router", "GET /api/data/{ticker}, /api/data/zillow/{zip}")
        Component(asset_router, "Assets Router", "FastAPI Router", "GET /api/assets/{search,case-shiller,suggest}")
        Component(session_router, "Sessions Router", "FastAPI Router", "CRUD /api/sessions")
        Component(settings_router, "Settings Router", "FastAPI Router", "GET/PUT /api/settings, cache mgmt, backups")
        Component(health_router, "Health Router", "FastAPI Router", "GET /api/health/sources")

        Component(reg_service, "Regression Service", "Python/SciPy/statsmodels", "Linear, OLS multi-factor, rolling regressions with ADF, VIF, Durbin-Watson diagnostics")
        Component(data_fetcher, "Data Fetcher", "Python/yfinance/fredapi", "Unified fetch with source detection, retry, dual Yahoo endpoints, FRED throttle")
        Component(cache_service, "Cache Service", "Python/SQLAlchemy", "Frequency-aware TTL, fresh/stale retrieval, upsert")
        Component(backup_service, "Backup Service", "Python", "SQLite file backup and restore")
        Component(transforms, "Transforms", "Python/Pandas", "Dataset alignment, frequency inference, time indexing")

        Component(schemas, "Schemas", "Pydantic", "Request/response models for all endpoints")
        Component(config, "Config", "Pydantic Settings", "FRED key, DB URL, cache TTLs")
    }

    ContainerDb(db, "SQLite", "", "cache, sessions, app_settings tables")
    System_Ext(yahoo, "Yahoo Finance")
    System_Ext(fred, "FRED API")
    System_Ext(zillow, "Zillow Research")

    Rel(reg_router, reg_service, "Calls")
    Rel(reg_router, data_fetcher, "Fetches data")
    Rel(reg_router, transforms, "Aligns datasets")
    Rel(data_router, data_fetcher, "Fetches data")
    Rel(asset_router, data_fetcher, "Uses ASSET_REGISTRY")
    Rel(session_router, db, "CRUD sessions")
    Rel(settings_router, db, "Read/write settings")
    Rel(settings_router, cache_service, "Cache stats/clear")
    Rel(settings_router, backup_service, "Backup/restore")
    Rel(health_router, yahoo, "Health check")
    Rel(health_router, fred, "Health check")
    Rel(health_router, zillow, "Health check")

    Rel(data_fetcher, cache_service, "Cache-first lookup, stale fallback")
    Rel(data_fetcher, yahoo, "yfinance lib + direct query1 API")
    Rel(data_fetcher, fred, "fredapi with 500ms throttle")
    Rel(data_fetcher, zillow, "Downloads public CSV")
    Rel(cache_service, db, "Read/write cache entries")
    Rel(config, db, "Reads FRED key from app_settings")
```

## Component Diagram — Frontend (Level 3)

```mermaid
C4Component
    title Component Diagram — Frontend SPA

    Container_Boundary(fe, "React Frontend") {

        Component(app, "App / Router", "React Router 7", "Routes: /, /settings, /help")

        Component(layout, "Layout Components", "React", "Header, Sidebar, OfflineBanner, LoadingSkeleton")
        Component(controls, "Control Components", "React", "AssetSelector, ComparePicker, DateRangePicker, RegressionMode, WindowSizeSlider")
        Component(charts, "Chart Components", "React/Plotly", "RegressionChart, ComparisonChart, ResidualChart, RollingChart, CompareChart")
        Component(results, "Results Components", "React", "StatsPanel, StatsInterpretation, DataQualityBadge, ExportButtons, AnnotationPanel")
        Component(pages, "Pages", "React", "AnalysisPage, SettingsPage, HelpPage, SetupWizard")

        Component(use_regression, "useRegression Hook", "React Hook", "Analysis state, mode switching, run/reset, earnings overlay")
        Component(use_sessions, "useSessions Hook", "React Hook", "Save/load/delete analysis sessions")
        Component(use_search, "useAssetSearch Hook", "React Hook", "Asset search with offline fallback")
        Component(use_health, "useSourceHealth Hook", "React Hook", "Polls data source availability")

        Component(api_client, "API Client", "Axios", "All backend calls: data, regression, sessions, settings, health")
        Component(theme_ctx, "ThemeContext", "React Context", "Dark/light mode, persisted to localStorage")
        Component(offline_ctx, "OfflineContext", "React Context", "Tracks source health for offline awareness")
        Component(utils, "Utilities", "JS", "Formatters, CSV/JSON/PNG export")
    }

    Container_Ext(backend, "Backend API")

    Rel(app, pages, "Renders")
    Rel(pages, layout, "Uses")
    Rel(pages, controls, "Uses")
    Rel(pages, charts, "Uses")
    Rel(pages, results, "Uses")

    Rel(pages, use_regression, "Analysis state")
    Rel(pages, use_sessions, "Session mgmt")
    Rel(controls, use_search, "Asset search")
    Rel(layout, use_health, "Offline detection")

    Rel(use_regression, api_client, "Calls regression & data APIs")
    Rel(use_sessions, api_client, "Calls session APIs")
    Rel(use_search, api_client, "Calls asset search API")
    Rel(use_health, api_client, "Calls health API")

    Rel(api_client, backend, "HTTP/JSON", "Axios, 30s timeout")

    Rel(layout, theme_ctx, "Reads theme")
    Rel(layout, offline_ctx, "Reads source status")
    Rel(results, utils, "Export data")
```

## Data Flow Summary

```
User → Frontend SPA → API Client (Axios)
                            │
                            ▼
                     FastAPI Backend
                     ┌──────────────────────────┐
                     │  Routers                  │
                     │  ├─ regression (4 modes)  │
                     │  ├─ data (ticker/zillow)  │
                     │  ├─ assets (search)       │
                     │  ├─ sessions (CRUD)       │
                     │  ├─ settings (config)     │
                     │  └─ health (source check) │
                     │                           │
                     │  Services                 │
                     │  ├─ DataFetcher           │──→ Yahoo Finance (dual endpoint + retry)
                     │  │   ├─ cache-first       │──→ FRED API (throttled 500ms + retry)
                     │  │   └─ stale fallback    │──→ Zillow CSV (retry)
                     │  ├─ RegressionService     │
                     │  │   └─ ADF/VIF/DW tests  │
                     │  ├─ CacheService          │──→ SQLite (cache table)
                     │  └─ Transforms            │
                     │       └─ align datasets   │
                     └──────────────────────────┘
```

## Key Architectural Decisions

| Decision | Detail |
|---|---|
| **Cache-first** | All data fetches check SQLite cache before hitting external APIs |
| **Frequency-aware TTL** | Daily data: 24h, Monthly/quarterly: 7 days |
| **Stale fallback** | If API fails after retries, serve stale cached data with `is_stale` flag |
| **Dual Yahoo endpoints** | yfinance library (query2) → direct API (query1) fallback |
| **FRED throttle** | Thread-safe 500ms minimum interval between FRED calls |
| **Exponential backoff** | tenacity: 3 attempts, 2-10s waits (Yahoo), 1-4s waits (FRED/Zillow) |
| **Concurrency cap** | ThreadPoolExecutor(max_workers=4) for Yahoo fetches |
| **Stationarity checks** | ADF test + auto-differencing for non-stationary time series |
| **Production deploy** | Docker Compose + Caddy reverse proxy with auto-SSL |
