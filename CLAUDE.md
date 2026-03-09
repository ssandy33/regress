# CLAUDE.md — Project Instructions

## Testing Requirements

- Every issue must have automated test coverage for all its acceptance criteria before the PR is merged.
- Tests must be written as part of the implementation, not as a separate follow-up step.
- If an AC is a manual/infrastructure step (e.g., "create an OAuth app"), document it in the test file as a skipped test or comment explaining why it's not automatable.
- Backend tests: `backend/tests/` using pytest (in-memory SQLite via conftest fixtures).
- Frontend tests: `frontend/e2e/` using Playwright for integration/e2e flows.
- Run backend tests: `cd backend && python -m pytest`
- Run frontend tests: `cd frontend && npx playwright test`
- CI runs both backend tests and frontend lint/build on every PR.

## Code Quality

- Never return raw exception messages (`str(e)`) in API responses — use generic error messages.
- Sanitize user input at system boundaries; trust internal code.
- No unused imports, variables, or dead code.
- Keep PRs focused — one issue per PR.

## Issue Management

- When creating an issue, determine its priority (critical, high, medium, low) and add a comment explaining the rationale for the chosen priority level.
