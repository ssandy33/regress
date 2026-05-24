"""Tests for the issue #298 per-test heuristic upgrade.

These cover ACs that the Wave 1 file-level heuristic could not satisfy.
Kept in a sibling file (separate from ``test_classify_tests.py``) because
the Wave 1 tests scaffold synthetic ``@pytest.mark.tdd_red`` decorators
inside string literals — the Wave 2 ``check_tdd_red`` gate's line-regex
scanner can false-positive on those literals when the host file appears
in a PR diff. Splitting keeps this file gate-clean and preserves the
plan's intent (AC-4 fixture coverage exists; the file location is an
implementation detail).

AC mapping (#298):

| AC | Test |
|---|---|
| AC-1 | test_per_test_classify_unit_when_only_helper_calls_in_mixed_file |
| AC-1 | test_per_test_classify_unit_when_file_imports_testclient_for_sibling |
| AC-2 | test_per_test_classify_integration_when_client_get_called_in_body |
| AC-2 | test_per_test_classify_integration_when_testclient_instantiated_in_body |
| AC-2 | test_per_test_classify_integration_when_fixture_consumes_client_transitively |
| AC-3 | test_per_test_classify_research_price_history_regression |
| AC-3 | test_per_test_classify_regression_corpus_counts_meet_ac3_targets |
| AC-4 | test_per_test_classify_unit_when_only_helper_calls_in_mixed_file (the mixed-class fixture) |

All tests are marked ``@pytest.mark.unit`` — the classifier is pytest
+ stdlib only, no FastAPI app, no DB.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts import classify_tests


REPO_BACKEND = Path(__file__).resolve().parent.parent  # backend/
REPO_TESTS = REPO_BACKEND / "tests"


def _write_test_file(path: Path, source: str) -> None:
    """Write a dedented test-fixture source file to ``path``."""
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-1 + AC-4 — per-test verdict overrides file-level imports
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_per_test_classify_unit_when_only_helper_calls_in_mixed_file(tmp_path):
    """AC-1 + AC-4: tests calling only private helpers stay unit even when the
    file imports ``app.main`` for sibling tests in the same module.

    This is the canonical AC-4 fixture: a single file with two test classes,
    one pure-helper (unit) and one ``client``-fixture-using (integration).
    Wave 1's file-level heuristic poisoned both classes to integration; the
    upgrade decides per-test.
    """
    f = tmp_path / "test_mixed.py"
    _write_test_file(
        f,
        """
        from app.main import app  # imported for a sibling class below
        from app.services import some_service as svc

        class TestPureHelpers:
            def test_calls_private_helper_only(self):
                # No client. No TestClient. No app. Just a helper call.
                result = svc._compute_something(1, 2)
                assert result == 3

            def test_more_helper_logic(self):
                assert svc._another_helper("x") == "X"

        class TestEndpointGroup:
            def test_via_client(self, client):
                # This one IS integration — uses the client fixture.
                resp = client.get("/api/something")
                assert resp.status_code == 200
        """,
    )
    scan = classify_tests.scan_file(f)
    by_qual = {r.qualname: r.suggested_tier for r in scan.tests}
    assert by_qual["TestPureHelpers.test_calls_private_helper_only"] == "unit"
    assert by_qual["TestPureHelpers.test_more_helper_logic"] == "unit"
    assert by_qual["TestEndpointGroup.test_via_client"] == "integration"
    # The file-level app.main import is STILL captured on the scan (for the
    # per-file report table) but no longer poisons the unit-class verdicts.
    assert scan.has_app_main_import is True


@pytest.mark.unit
def test_per_test_classify_unit_when_file_imports_testclient_for_sibling(tmp_path):
    """AC-1 reinforcement: ``from fastapi.testclient import TestClient`` at
    module scope does NOT push a sibling test into integration if that sibling
    never uses it. (Wave 1's file-level heuristic would have failed here.)"""
    f = tmp_path / "test_sibling.py"
    _write_test_file(
        f,
        """
        from fastapi.testclient import TestClient
        from app.services import calc

        def test_pure_math_unaffected_by_sibling_imports():
            assert calc.add(2, 3) == 5
        """,
    )
    scan = classify_tests.scan_file(f)
    record = scan.tests[0]
    assert record.suggested_tier == "unit"
    assert record.test_body_uses_client is False
    assert record.test_uses_client_fixture is False
    # File flag still captured for the report.
    assert scan.has_testclient_import is True


# ---------------------------------------------------------------------------
# AC-2 — body-walk detects client.<verb>(...) or TestClient(...) inline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_per_test_classify_integration_when_client_get_called_in_body(tmp_path):
    """AC-2: a test whose body calls ``client.get(...)`` is integration even
    without taking the ``client`` fixture in its signature (e.g. resolves via
    ``self.client`` set in setUp)."""
    f = tmp_path / "test_body_client.py"
    _write_test_file(
        f,
        """
        class TestViaSelfClient:
            def test_uses_self_client_get(self):
                resp = self.client.get("/api/foo")
                assert resp.status_code == 200
        """,
    )
    scan = classify_tests.scan_file(f)
    record = scan.tests[0]
    assert record.suggested_tier == "integration"
    assert record.test_body_uses_client is True
    assert record.test_uses_client_fixture is False


@pytest.mark.unit
def test_per_test_classify_integration_when_testclient_instantiated_in_body(tmp_path):
    """AC-2: a test that instantiates ``TestClient(...)`` in-body is integration."""
    f = tmp_path / "test_inline_testclient.py"
    _write_test_file(
        f,
        """
        from fastapi.testclient import TestClient
        from app.main import app

        def test_builds_its_own_client():
            with TestClient(app) as c:
                resp = c.get("/health")
                assert resp.status_code == 200
        """,
    )
    scan = classify_tests.scan_file(f)
    record = scan.tests[0]
    assert record.suggested_tier == "integration"
    assert record.test_body_uses_client is True


@pytest.mark.unit
def test_per_test_classify_integration_when_fixture_consumes_client_transitively(tmp_path):
    """Regression: a test taking a fixture that itself takes ``client`` stays
    integration — preserved Wave 1 behavior (#265)."""
    f = tmp_path / "test_transitive.py"
    _write_test_file(
        f,
        """
        import pytest

        @pytest.fixture
        def authed_client(client):
            return client

        def test_via_authed_client(authed_client):
            # Notice: body does NOT call any client method; the signal is the
            # fixture-name match propagated through known_client_fixtures.
            assert authed_client is not None
        """,
    )
    scan = classify_tests.scan_file(f)
    # The fixture itself is filtered out (decorated with @pytest.fixture).
    qualnames = {r.qualname for r in scan.tests}
    assert qualnames == {"test_via_authed_client"}
    record = scan.tests[0]
    assert record.suggested_tier == "integration"
    assert record.test_uses_client_fixture is True


# ---------------------------------------------------------------------------
# AC-3 — corpus-level regression
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_per_test_classify_research_price_history_regression():
    """AC-3 regression anchor: the canonical mixed-file case from #298.

    ``test_research_price_history.py`` mixes ``TestTradeEventMapping`` (6 unit
    tests on private helpers) + ``TestWindowResolution`` (3 unit tests) with
    ``TestPriceHistoryEndpoint`` (uses ``client`` fixture). Wave 1 over-flagged
    all 21 tests as integration; the upgrade must classify the first 9 as
    ``unit``.
    """
    target = REPO_TESTS / "test_research_price_history.py"
    if not target.exists():
        pytest.skip(f"missing canonical regression file {target}")
    scan = classify_tests.scan_file(target)
    by_qual = {r.qualname: r.suggested_tier for r in scan.tests}
    helper_class_tests = [q for q in by_qual if q.startswith("TestTradeEventMapping.")]
    window_class_tests = [q for q in by_qual if q.startswith("TestWindowResolution.")]
    assert len(helper_class_tests) == 6, (
        f"expected 6 TestTradeEventMapping tests, got {len(helper_class_tests)}"
    )
    assert len(window_class_tests) == 3, (
        f"expected 3 TestWindowResolution tests, got {len(window_class_tests)}"
    )
    for q in helper_class_tests + window_class_tests:
        assert by_qual[q] == "unit", f"{q} should be unit, got {by_qual[q]}"
    endpoint_tests = [q for q in by_qual if q.startswith("TestPriceHistoryEndpoint.")]
    assert endpoint_tests, "expected TestPriceHistoryEndpoint tests in the file"
    for q in endpoint_tests:
        assert by_qual[q] == "integration", (
            f"{q} should be integration, got {by_qual[q]}"
        )


@pytest.mark.unit
def test_per_test_classify_regression_corpus_counts_meet_ac3_targets():
    """AC-3: re-running the classifier against the real backend test corpus
    produces >=1019 unit / <=461 integration.

    The plan's locked baseline (pre-upgrade) was 958 unit / 462 integration /
    1420 total. After the #298 per-test heuristic upgrade, 60+ tests reclassify
    from integration -> unit. This test pins the AC-3 floor/ceiling and acts as
    a corpus-level guard against future regressions in the per-test heuristic.

    The corpus total is NOT pinned to an exact number — adding new tests is
    expected over time; the invariant is that the upgrade reclassifies, never
    creates ghost records. We assert the two tiers partition the scanned set.
    """
    if not REPO_TESTS.is_dir():
        pytest.skip(f"missing backend tests dir {REPO_TESTS}")
    scans = classify_tests.scan_directory(REPO_TESTS)
    counts = {"unit": 0, "integration": 0}
    total = 0
    for scan in scans:
        for record in scan.tests:
            total += 1
            counts[record.suggested_tier] += 1
    assert counts["unit"] >= 1019, (
        f"AC-3 floor: unit >= 1019, got {counts['unit']}"
    )
    assert counts["integration"] <= 461, (
        f"AC-3 ceiling: integration <= 461, got {counts['integration']}"
    )
    # Invariant: the two tiers partition the corpus (no third bucket).
    assert counts["unit"] + counts["integration"] == total
