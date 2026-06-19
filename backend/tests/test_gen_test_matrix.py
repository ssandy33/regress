"""Unit tests for ``backend/scripts/gen_test_matrix.py`` (ADR #356).

Pure-Python: no FastAPI app, no DB session, no network. Each test scaffolds a
throwaway ``test_*.py`` source in ``tmp_path``, runs the AST collector against
it with an explicit (offline) known-AC registry, and asserts on the resulting
``Matrix`` / coverage analysis / rendered markdown.

The generator's known-AC registry is normally the committed, issue-derived
``ac_registry.json`` (read by ``load_registry()``); these tests pass an explicit
``known`` mapping to ``collect`` so they never touch that file or the network.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts import gen_test_matrix as gtm


# ``@pytest.mark.ac`` assembled from substrings so the literal decorator never
# appears verbatim at line-start in THIS file (keeps the scaffolds honest and
# avoids any future gate that greps for marker literals; mirrors the tdd_red
# convention in test_classify_tests.py).
_AC = "@pytest.mark." + "ac"


def _write(path: Path, source: str) -> Path:
    """Dedent + write a scaffold test source, returning the path."""
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# AST collection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scan_file_extracts_single_ac_tag(tmp_path):
    """A test tagged with one AC-ID yields one TestRef carrying that ID + layer."""
    f = _write(
        tmp_path / "test_one.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_alpha():
            assert True
        """,
    )
    refs = gtm.scan_file(f)
    assert len(refs) == 1
    assert refs[0].qualname == "test_alpha"
    assert refs[0].layer == "unit"
    assert refs[0].ac_ids == ("349-AC1",)


@pytest.mark.unit
def test_scan_file_extracts_multiple_ac_ids(tmp_path):
    """A single ``ac(...)`` with several IDs collects all of them."""
    f = _write(
        tmp_path / "test_multi.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC11", "349-AC12")
        def test_guard():
            assert True
        """,
    )
    refs = gtm.scan_file(f)
    assert refs[0].ac_ids == ("349-AC11", "349-AC12")
    assert refs[0].layer == "integration"


@pytest.mark.unit
def test_scan_file_ignores_untagged_tests(tmp_path):
    """Tests with no ``ac`` marker are not collected (only AC-tagged ones)."""
    f = _write(
        tmp_path / "test_none.py",
        """
        import pytest

        @pytest.mark.unit
        def test_plain():
            assert True
        """,
    )
    assert gtm.scan_file(f) == []


@pytest.mark.unit
def test_scan_file_collects_class_scoped_methods(tmp_path):
    """An AC tag on a method inside ``class Test...`` surfaces as Class.method."""
    f = _write(
        tmp_path / "test_cls.py",
        f"""
        import pytest

        class TestGroup:
            @pytest.mark.unit
            {_AC}("349-AC3")
            def test_inner(self):
                assert True
        """,
    )
    refs = gtm.scan_file(f)
    assert refs[0].qualname == "TestGroup.test_inner"
    assert refs[0].ac_ids == ("349-AC3",)


@pytest.mark.unit
def test_scan_file_skips_unparseable_source(tmp_path):
    """A syntactically broken file is skipped (returns []) rather than raising."""
    f = tmp_path / "test_broken.py"
    f.write_text("def test_x(:\n    pass\n", encoding="utf-8")
    assert gtm.scan_file(f) == []


# ---------------------------------------------------------------------------
# collect() — registry + unknown-AC detection
# ---------------------------------------------------------------------------


def _collect(tmp_path: Path, known: dict[str, str]) -> gtm.Matrix:
    return gtm.collect(tmp_path, known=known)


@pytest.mark.unit
def test_collect_maps_known_acs_to_tests(tmp_path):
    """collect() builds an AC-ID -> covering TestRef mapping from the dir."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_a():
            assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "first", "349-AC2": "second"})
    assert [r.qualname for r in matrix.by_ac["349-AC1"]] == ["test_a"]
    assert matrix.by_ac.get("349-AC2", []) == []


@pytest.mark.unit
def test_collect_flags_unknown_ac_ids(tmp_path):
    """An AC-ID referenced by a test but absent from the registry is 'unknown'."""
    _write(
        tmp_path / "test_typo.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC99")
        def test_typo():
            assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "known"})
    assert "349-AC99" in matrix.unknown_ac_ids


@pytest.mark.unit
def test_collect_dedups_same_test_across_ac_ids(tmp_path):
    """A test tagged with the same AC twice appears once under that AC."""
    _write(
        tmp_path / "test_dup.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1", "349-AC1")
        def test_dup():
            assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    assert len(matrix.by_ac["349-AC1"]) == 1


# ---------------------------------------------------------------------------
# Coverage analysis — uncovered / thin tier / meta-AC
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_uncovered_known_ac_detected(tmp_path):
    """A known AC-ID with zero covering tests is reported as uncovered."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_a():
            assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "covered", "349-AC2": "orphan"})
    assert gtm.uncovered_known_acs(matrix) == ["349-AC2"]


@pytest.mark.unit
def test_thin_tier_flags_unit_only_ac(tmp_path):
    """A covered AC with no integration test is flagged as thin (warning set)."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_unit_only():
            assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    assert gtm.thin_tier_known_acs(matrix) == ["349-AC1"]


@pytest.mark.unit
def test_thin_tier_clears_when_integration_present(tmp_path):
    """An AC with at least one integration test is NOT thin."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_unit(): assert True

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_integ(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    assert gtm.thin_tier_known_acs(matrix) == []


@pytest.mark.unit
def test_meta_ac_satisfied_with_unit_and_integration(tmp_path):
    """349-AC13 is satisfied when the suite carries unit AND integration #349 tests."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_u(): assert True

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_i(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k", "349-AC13": "meta"})
    assert gtm.uncovered_known_acs(matrix) == []


@pytest.mark.unit
def test_meta_ac_unsatisfied_without_integration(tmp_path):
    """349-AC13 is uncovered when only unit #349 tests exist (no integration)."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_u(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k", "349-AC13": "meta"})
    assert "349-AC13" in gtm.uncovered_known_acs(matrix)


# ---------------------------------------------------------------------------
# Coverage gate (check)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_passes_when_all_covered(tmp_path, capsys):
    """check() returns 0 when every known AC has a covering test."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    rc = gtm.check(matrix)
    assert rc == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.unit
def test_check_hard_fails_on_uncovered_ac(tmp_path, capsys):
    """check() returns 1 and names the uncovered AC-ID."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k", "349-AC2": "missing"})
    rc = gtm.check(matrix)
    out = capsys.readouterr().out
    assert rc == 1
    assert "349-AC2" in out
    assert "uncovered" in out


@pytest.mark.unit
def test_check_warns_but_passes_on_thin_tier(tmp_path, capsys):
    """A unit-only (thin) AC warns but does NOT fail the gate (OQ3)."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    rc = gtm.check(matrix)
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARN" in out and "integration tier" in out


@pytest.mark.unit
def test_check_warns_but_passes_on_unknown_ac(tmp_path, capsys):
    """A typo'd / dangling AC-ID warns but does NOT fail the gate (OQ4)."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC1", "349-AC404")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    rc = gtm.check(matrix)
    out = capsys.readouterr().out
    assert rc == 0
    assert "349-AC404" in out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_markdown_has_summary_and_rows(tmp_path):
    """The rendered matrix carries the coverage summary and a row per known AC."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "first AC", "349-AC2": "second AC"})
    md = gtm.render_markdown(matrix)
    assert "# Test traceability matrix" in md
    assert "Covered: **1/2**" in md
    assert "`349-AC1`" in md and "test_a" in md
    # The uncovered AC is rendered with the NO COVERAGE sentinel.
    assert "**— NO COVERAGE —**" in md
    assert "349-AC2" in md


@pytest.mark.unit
def test_render_markdown_lists_thin_and_unknown_sections(tmp_path):
    """Thin-tier and unknown-AC sections appear when those conditions hold."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.unit
        {_AC}("349-AC1", "349-AC777")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    md = gtm.render_markdown(matrix)
    assert "Thin coverage" in md
    assert "Unknown AC-IDs referenced by tests" in md
    assert "349-AC777" in md


# ---------------------------------------------------------------------------
# Output sinks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_matrix_file_roundtrips(tmp_path):
    """write_matrix_file writes the rendered markdown to the given path."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    out_path = tmp_path / "out" / "TEST-MATRIX.md"
    gtm.write_matrix_file(matrix, out_path)
    assert out_path.is_file()
    assert "Test traceability matrix" in out_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_write_job_summary_appends_when_env_set(tmp_path, monkeypatch):
    """write_job_summary appends to $GITHUB_STEP_SUMMARY when the var is set."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert gtm.write_job_summary(matrix) is True
    assert "Test traceability matrix" in summary.read_text(encoding="utf-8")


@pytest.mark.unit
def test_write_job_summary_noop_when_env_unset(tmp_path, monkeypatch):
    """Locally (no $GITHUB_STEP_SUMMARY) write_job_summary is a no-op returning False."""
    matrix = _collect(tmp_path, {"349-AC1": "k"})
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert gtm.write_job_summary(matrix) is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_main_check_mode_does_not_write_file(tmp_path):
    """``--check`` (alone) must not write TEST-MATRIX.md — side-effect-free gate."""
    _write(
        tmp_path / "test_a.py",
        f"""
        import pytest

        @pytest.mark.integration
        {_AC}("349-AC1")
        def test_a(): assert True
        """,
    )
    out_path = tmp_path / "TEST-MATRIX.md"
    # Patch the registry read so the gate is offline + deterministic.
    import scripts.gen_test_matrix as mod

    original = mod.known_ac_ids
    mod.known_ac_ids = lambda: {"349-AC1": "k"}  # type: ignore[assignment]
    try:
        rc = gtm.main(
            ["--check", "--tests-dir", str(tmp_path), "--out", str(out_path)]
        )
    finally:
        mod.known_ac_ids = original  # type: ignore[assignment]
    assert rc == 0
    assert not out_path.exists()
