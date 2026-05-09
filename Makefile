.PHONY: reconcile-positions test-backend test-frontend

# Re-derive Position lifecycle state from each position's trade ledger.
# Defaults to a dry-run; pass ARGS=--apply to commit changes.
#
#   make reconcile-positions
#   make reconcile-positions ARGS=--apply
reconcile-positions:
	cd backend && python -m scripts.reconcile_positions $(ARGS)

# Run the backend pytest suite (in-memory SQLite via conftest fixtures).
test-backend:
	cd backend && python -m pytest

# Run the frontend Playwright e2e suite.
test-frontend:
	cd frontend && npx playwright test
