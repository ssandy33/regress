# CLAUDE.md — Project Instructions

## Project Structure

- **Backend**: `backend/app/` — FastAPI, Python 3.13, SQLite, venv at `backend/.venv/`
- **Frontend**: `frontend/` — Next.js 15 App Router, React, Tailwind CSS
- **Tests**: `backend/tests/` (pytest), `frontend/e2e/` (Playwright)
- **Deploy**: `docker-compose.prod.yml`, `deploy/deploy.sh`, Caddy reverse proxy
- **CI**: `.github/workflows/ci.yml`

## Commands

- Backend tests: `cd backend && source .venv/bin/activate && python -m pytest`
- Frontend dev: `cd frontend && npm run dev`
- Frontend build: `cd frontend && npm run build`
- Frontend e2e: `cd frontend && npx playwright test`
- Docker prod: `docker compose -f docker-compose.prod.yml up -d --build`

## Testing Requirements

- Every issue must have automated test coverage for all its acceptance criteria before the PR is merged.
- If an AC is a manual/infrastructure step (e.g., "create an OAuth app"), document it in the test file as a skipped test or comment explaining why it's not automatable.
- Backend tests use in-memory SQLite via `conftest.py` fixtures.
- Run both backend tests and frontend build before pushing.

## Git & PR Workflow

- Branch naming: `feature/description` or `fix/description`
- Commit messages: imperative tense, explain "why" not "what", end with `Co-Authored-By` line
- One issue per PR — keep PRs focused
- Always address CodeRabbit review comments before merging
- Create follow-up issues for out-of-scope findings rather than expanding PR scope
- Never commit `.env` files or secrets — `.env` is gitignored

## Architecture Patterns

- **Config**: pydantic `Settings` with env var + DB `AppSetting` fallback (see `get_fred_api_key()` pattern in `config.py`)
- **Health checks**: `_check_*()` functions in `routers/health.py` return `{available, error}`
- **Settings health**: `/api/settings/health/<source>` endpoint pattern
- **Auth**: opt-in via env vars — app works fully without OAuth credentials (graceful degradation)
- **Error responses**: sanitize to generic messages in API responses, log details server-side
- **Caching**: `CacheEntry` table for data cache, two-tier (in-memory + SQLite) for Alpha Vantage

## Security

- Never return `str(e)` in API responses — use generic error messages
- No user input in file path expressions — use allowlist lookups (glob pattern matching)
- Don't expose secrets to containers that don't need them (principle of least privilege)
- `chmod 600` on `.env` files in production
- Sanitize user input at system boundaries; trust internal code
- URL-encode OAuth parameters per spec

## Code Quality

- No unused imports, variables, or dead code
- No f-strings without placeholders
- Remove unused CLI args
- Don't add comments, docstrings, or type annotations to code you didn't change
- Avoid over-engineering — only make changes directly requested or clearly necessary

## Stack & Dependencies

- **Backend**: FastAPI, SQLAlchemy, pydantic, statsmodels, httpx
- **Frontend**: Next.js (App Router), React, Tailwind CSS, NextAuth.js
- **Data sources**: FRED API, Alpha Vantage, Schwab API
- **Removed**: yfinance (fully removed — use Alpha Vantage for earnings data)
