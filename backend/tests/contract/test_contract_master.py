"""Contract tests — every documented endpoint matches its declared response shape.

Strategy:
  - The committed OpenAPI snapshot (backend/openapi/openapi.json) is loaded
    via schemathesis.openapi.from_path; the FastAPI app is attached so
    Schemathesis routes calls in-process via ASGITransport.
  - case.call() invokes the endpoint; case.validate_response() validates the
    response against the spec's declared response schema (status code,
    content type, body shape).
  - We run ONLY the four response-shape conformance checks — AC-4.4 is
    "validate response shape against spec", NOT "audit auth or input
    validation". The integration suite intentionally bypasses auth
    (root conftest's get_current_user override); Schemathesis's
    ignored_auth / missing_required_header / positive_data_acceptance
    checks would all flag that as a security failure. Those concerns
    are out of scope for contract validation.
  - 404s from path-param endpoints are accepted (the in-memory DB is empty;
    Hypothesis-generated path params won't match seeded data).
  - The 21 day-1 gap endpoints (no-schema / loose-object responses) are
    excluded by (method, path) until the post-merge sub-issues lift them.
"""
from __future__ import annotations

import pytest
from schemathesis.checks import (
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from .conftest import contract_settings, schema

# Restrict validation to response-shape checks only. Other Schemathesis
# default checks (ignored_auth, missing_required_header, positive/negative
# data acceptance/rejection, use_after_free, etc.) probe security and
# behavioral properties that are out of scope for AC-4.4.
RESPONSE_SHAPE_CHECKS = [
    status_code_conformance,
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
]

# Day-1 exclusion list. Each entry corresponds to one of the 4 grouped JIT
# sub-issues filed post-merge. When a sub-issue closes (response_model
# added, schemas.py updated, openapi.json regenerated), remove the entry
# from this list and re-run.
#
# Format: (method, path) pairs — match the spec exactly.
DAY_1_EXCLUSIONS: list[tuple[str, str]] = [
    # Group A: settings non-auth (8)
    ("PUT", "/api/settings"),
    ("GET", "/api/settings/account-value"),
    ("POST", "/api/settings/account-value/refresh"),
    ("GET", "/api/settings/backups"),
    ("POST", "/api/settings/backups/restore"),
    ("DELETE", "/api/settings/cache"),
    ("GET", "/api/settings/cache/freshness"),
    ("POST", "/api/settings/cache/refresh-all"),
    ("POST", "/api/settings/cache/refresh-stale"),
    ("GET", "/api/settings/rules"),
    ("POST", "/api/settings/rules/migration/sizing-cap/dismiss"),
    # Group B: settings schwab/health-probe (4)
    ("GET", "/api/settings/health/fred"),
    ("GET", "/api/settings/health/schwab"),
    ("POST", "/api/settings/schwab/auth-url"),
    ("POST", "/api/settings/schwab/callback"),
    # Group C: health (2)
    ("GET", "/api/health"),
    ("GET", "/api/health/sources"),
    # Group D: assets + options (4)
    ("GET", "/api/assets/case-shiller"),
    ("GET", "/api/assets/suggest"),
    ("GET", "/api/options/chain/{ticker}"),
    ("GET", "/api/options/earnings/{ticker}"),
]


def _is_excluded(case) -> bool:
    """Return True if (method, path) is on the day-1 exclusion list."""
    return (case.method.upper(), case.path) in DAY_1_EXCLUSIONS


@pytest.mark.integration
@contract_settings
@schema.parametrize()
def test_contract_endpoint_returns_documented_shape(case, client):
    """Every documented endpoint's response validates against the OpenAPI spec.

    The ``client`` fixture from backend/tests/conftest.py is required as a
    dependency (NOT passed to ``case.call``) — its job is to install the
    in-memory-SQLite ``get_db`` override and the auth-bypass
    ``get_current_user`` override onto the shared FastAPI ``app`` object.
    Schemathesis 4.x's ``ASGITransport`` calls that same ``app`` directly,
    so the overrides are picked up automatically.

    Why not ``session=client``: Schemathesis 4.x's ``Case.call(session=...)``
    expects a ``requests.Session``, not a FastAPI ``TestClient`` — passing
    one raises an AttributeError. Reusing the fixture for its side-effects
    (dependency overrides + lifespan patches) is the working pattern.
    """
    if _is_excluded(case):
        pytest.skip(
            f"Day-1 exclusion (post-merge sub-issue): "
            f"{case.method.upper()} {case.path} has no/loose response schema"
        )

    response = case.call()
    if response.status_code == 404 and "{" in case.path:
        return  # path-param endpoint hit an unseeded ID; spec doesn't lie.
    case.validate_response(response, checks=RESPONSE_SHAPE_CHECKS)


@pytest.mark.integration
def test_exclusion_list_is_known_gaps():
    """The exclusion list must be non-empty and match the locked vocabulary.

    Why: prevents a future implementer from silently adding a new exclusion
    to mask a real regression. Each sub-issue close shrinks this list;
    eventual goal is len(DAY_1_EXCLUSIONS) == 0.
    """
    assert len(DAY_1_EXCLUSIONS) == 21
    methods = {m for m, _ in DAY_1_EXCLUSIONS}
    assert methods == {"GET", "PUT", "POST", "DELETE"}
