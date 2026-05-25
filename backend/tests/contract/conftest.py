"""Schemathesis schema loader for contract tests.

Loads the committed OpenAPI snapshot at backend/openapi/openapi.json
(NOT the runtime-emitted spec — Wave 1 made the committed snapshot the
source of truth). Attaches the FastAPI ASGI app so Schemathesis routes
calls in-process via ASGITransport — no live server, faster, isolated.

The root backend/tests/conftest.py `client` fixture installs the same
in-memory-SQLite + auth-bypass dependency_overrides onto the SAME `app`
object that this module references. Tests that depend on `client` ensure
those overrides are active when Schemathesis fires its ASGI calls.
"""
from __future__ import annotations

from pathlib import Path

import schemathesis
from hypothesis import HealthCheck, settings as hypothesis_settings

from app.main import app

# Spec path resolution: relative to this conftest's parent's parent (= backend/)
SPEC_PATH = Path(__file__).parent.parent.parent / "openapi" / "openapi.json"


# Load the committed snapshot from disk (source of truth per PRD #262).
# Then attach the FastAPI app so .transport auto-resolves to ASGITransport
# (Schemathesis 4.x: schema.transport is derived from schema.app).
schema = schemathesis.openapi.from_path(str(SPEC_PATH))
schema.app = app


# Hypothesis tuning: cut max_examples drastically. We're testing "does the
# response shape match the spec?" not "find a Hypothesis-generated edge
# case". 5 examples per endpoint × ~63 endpoints = ~315 calls; should stay
# well inside the 2-min backend-integration suite budget.
contract_settings = hypothesis_settings(
    max_examples=5,
    deadline=None,  # in-process ASGI is fast but not predictable enough for default 200ms
    # The `client` fixture is function-scoped and intentionally NOT reset
    # between Hypothesis-generated cases — we want its dependency_overrides
    # to remain active for every call inside the test. Suppressing the
    # health check is the documented Hypothesis pattern for this case.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
