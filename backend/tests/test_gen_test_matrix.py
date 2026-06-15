"""Tests for ``backend/scripts/gen_test_matrix.py`` (test-traceability ADR).

The generator is application tooling, so its tests are real pytest tests in
``backend/tests/``. They are themselves ``@pytest.mark.unit`` (pure-Python: no
FastAPI app, no DB session, no network — they parse synthetic ``test_*.py``
files in ``tmp_path`` and assert on the in-memory matrix / rendered markdown).

AC test list (test-traceability ADR Decisions 2–4):

| Concern | Test |
|---|---|
| AST collection of single-AC tag | test_collects_single_ac_tag |
| AST collection of multi-AC tag | test_collects_multiple_ac_ids_from_one_decorator |
| Layer is read from the classifier marker | test_records_classifier_layer |
| Class-scoped test methods are walked | test_collects_class_scoped_test |
| Untagged tests are ignored | test_ignores_untagged_tests |
| Unknown AC-ID surfaced as typo, not registry | test_unknown_ac_id_flagged |
| --check passes when all known ACs covered | test_check_passes_when_all_known_acs_covered |
| --check fails when a known AC has zero tests | test_check_fails_on_uncovered_known_ac |
| Meta-AC (349-AC13) needs unit AND integration | test_meta_ac_requires_both_tiers |
| Rendered MD lists no-coverage section | test_render_lists_uncovered_section |
| Rendered MD shows covering tests per AC | test_render_shows_covering_tests |
| Job summary written when env var set | test_job_summary_written_when_env_set |
| Job summary skipped when env var absent | test_job_summary_skipped_without_env |
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts import gen_test_matrix as gtm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_test_file(tmp_path: Path, name: str, body: str) -> Path:
    """Write a synthetic ``test_*.py`` into ``tmp_path`` and return its path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# AST collection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_collects_single_ac_tag(tmp_path):
    _write_test_file(
        tmp_path,
        "test_sample.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("349-AC1")
        def test_one():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert len(matrix.tests) == 1
    ref = matrix.tests[0]
    assert ref.qualname == "test_one"
    assert ref.ac_ids == ("349-AC1",)
    assert ref.file == "test_sample.py"


@pytest.mark.unit
def test_collects_multiple_ac_ids_from_one_decorator(tmp_path):
    _write_test_file(
        tmp_path,
        "test_multi.py",
        """
        import pytest

        @pytest.mark.integration
        @pytest.mark.ac("349-AC1", "349-AC2", "349-AC3")
        def test_three():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert matrix.tests[0].ac_ids == ("349-AC1", "349-AC2", "349-AC3")
    # Each AC indexes the same test.
    for ac in ("349-AC1", "349-AC2", "349-AC3"):
        assert matrix.by_ac[ac][0].qualname == "test_three"


@pytest.mark.unit
def test_records_classifier_layer(tmp_path):
    _write_test_file(
        tmp_path,
        "test_layers.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("349-AC1")
        def test_u():
            assert True

        @pytest.mark.integration
        @pytest.mark.ac("349-AC2")
        def test_i():
            assert True

        @pytest.mark.ac("349-AC3")
        def test_unclassified():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    layers = {r.qualname: r.layer for r in matrix.tests}
    assert layers["test_u"] == "unit"
    assert layers["test_i"] == "integration"
    assert layers["test_unclassified"] == "unclassified"


@pytest.mark.unit
def test_collects_class_scoped_test(tmp_path):
    _write_test_file(
        tmp_path,
        "test_class.py",
        """
        import pytest

        class TestGroup:
            @pytest.mark.unit
            @pytest.mark.ac("349-AC1")
            def test_method(self):
                assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert matrix.tests[0].qualname == "TestGroup.test_method"


@pytest.mark.unit
def test_ignores_untagged_tests(tmp_path):
    _write_test_file(
        tmp_path,
        "test_mixed.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("349-AC1")
        def test_tagged():
            assert True

        @pytest.mark.unit
        def test_untagged():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert len(matrix.tests) == 1
    assert matrix.tests[0].qualname == "test_tagged"


@pytest.mark.unit
def test_unknown_ac_id_flagged(tmp_path):
    _write_test_file(
        tmp_path,
        "test_typo.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("349-AC99")
        def test_typo():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert "349-AC99" in matrix.unknown_ac_ids


# ---------------------------------------------------------------------------
# Coverage gate (--check)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_passes_when_all_known_acs_covered(tmp_path, monkeypatch):
    """A registry whose every AC has a covering test passes --check (exit 0)."""
    monkeypatch.setattr(
        gtm, "KNOWN_AC_IDS", {"X-AC1": "first", "X-AC2": "second"}
    )
    monkeypatch.setattr(gtm, "META_AC_IDS", frozenset())
    _write_test_file(
        tmp_path,
        "test_cov.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("X-AC1", "X-AC2")
        def test_both():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert gtm.uncovered_known_acs(matrix) == []
    assert gtm.check(matrix) == 0


@pytest.mark.unit
def test_check_fails_on_uncovered_known_ac(tmp_path, monkeypatch):
    """A known AC with zero covering tests fails --check (exit 1)."""
    monkeypatch.setattr(
        gtm, "KNOWN_AC_IDS", {"X-AC1": "first", "X-AC2": "uncovered"}
    )
    monkeypatch.setattr(gtm, "META_AC_IDS", frozenset())
    _write_test_file(
        tmp_path,
        "test_partial.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("X-AC1")
        def test_only_one():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert gtm.uncovered_known_acs(matrix) == ["X-AC2"]
    assert gtm.check(matrix) == 1


@pytest.mark.unit
def test_meta_ac_requires_both_tiers(tmp_path, monkeypatch):
    """349-AC13 is satisfied only when BOTH a unit and integration #349 test exist."""
    monkeypatch.setattr(gtm, "KNOWN_AC_IDS", {"349-AC13": "meta coverage"})
    monkeypatch.setattr(gtm, "META_AC_IDS", frozenset({"349-AC13"}))

    # Unit-only #349 test: meta-AC NOT satisfied.
    _write_test_file(
        tmp_path,
        "test_unit_only.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("349-AC1")
        def test_u():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert gtm.uncovered_known_acs(matrix) == ["349-AC13"]

    # Add an integration #349 test: now satisfied.
    _write_test_file(
        tmp_path,
        "test_integ.py",
        """
        import pytest

        @pytest.mark.integration
        @pytest.mark.ac("349-AC2")
        def test_i():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert gtm.uncovered_known_acs(matrix) == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_lists_uncovered_section(tmp_path, monkeypatch):
    monkeypatch.setattr(gtm, "KNOWN_AC_IDS", {"X-AC1": "covered", "X-AC2": "missing"})
    monkeypatch.setattr(gtm, "META_AC_IDS", frozenset())
    _write_test_file(
        tmp_path,
        "test_r.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("X-AC1")
        def test_a():
            assert True
        """,
    )
    md = gtm.render_markdown(gtm.collect(tmp_path))
    assert "Known AC-IDs with NO coverage" in md
    assert "`X-AC2`" in md
    assert "Covered: **1/2**" in md


@pytest.mark.unit
def test_render_shows_covering_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(gtm, "KNOWN_AC_IDS", {"X-AC1": "covered"})
    monkeypatch.setattr(gtm, "META_AC_IDS", frozenset())
    _write_test_file(
        tmp_path,
        "test_show.py",
        """
        import pytest

        @pytest.mark.integration
        @pytest.mark.ac("X-AC1")
        def test_visible():
            assert True
        """,
    )
    md = gtm.render_markdown(gtm.collect(tmp_path))
    assert "test_visible" in md
    assert "integration" in md
    assert "test_show.py" in md


# ---------------------------------------------------------------------------
# Output sinks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_job_summary_written_when_env_set(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(gtm, "KNOWN_AC_IDS", {"X-AC1": "covered"})
    monkeypatch.setattr(gtm, "META_AC_IDS", frozenset())
    _write_test_file(
        tmp_path,
        "test_s.py",
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.ac("X-AC1")
        def test_a():
            assert True
        """,
    )
    matrix = gtm.collect(tmp_path)
    assert gtm.write_job_summary(matrix) is True
    assert "Test traceability matrix" in summary.read_text(encoding="utf-8")


@pytest.mark.unit
def test_job_summary_skipped_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    matrix = gtm.Matrix()
    assert gtm.write_job_summary(matrix) is False
