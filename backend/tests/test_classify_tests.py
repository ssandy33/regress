"""Tests for ``backend/scripts/classify_tests.py``.

Covers the AC test list in issue #265:

| AC | Test |
|---|---|
| AC-1.1 | test_pytest_ini_registers_three_markers |
| AC-1.1 | test_pytest_ini_addopts_excludes_tdd_red |
| AC-1.1 | test_pytest_ini_strict_markers_enabled |
| AC-1.2 | test_classifier_finds_marked_tests |
| AC-1.2 | test_classifier_rejects_unmarked |
| AC-1.2 | test_classifier_rejects_double_marked |
| AC-1.2 | test_classifier_accepts_tdd_red |
| AC-1.2 | test_classifier_prints_counts |
| AC-1.2 | test_classifier_exit_code_clean_repo |
| AC-1.3 | test_report_mode_writes_sample_to_default_path |
| AC-1.3 | test_report_mode_lists_per_file_distribution |
| AC-1.4 | test_default_run_excludes_tdd_red (subprocess) |
| AC-1.5 | test_unit_and_integration_partitions_disjoint (subprocess) |

The classifier is application code, not just a script, so its tests are
real pytest tests in ``backend/tests/``. They are themselves marked
``@pytest.mark.unit`` (no FastAPI app, no DB) per the partition they
enforce.
"""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts import classify_tests


REPO_BACKEND = Path(__file__).resolve().parent.parent  # backend/
PYTEST_INI = REPO_BACKEND / "pytest.ini"


# ---------------------------------------------------------------------------
# AC-1.1 — pytest.ini registers markers, strict-markers, addopts
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pytest_ini_registers_three_markers():
    """pytest.ini declares unit / integration / tdd_red and nothing else as classifier markers."""
    assert PYTEST_INI.exists(), f"missing {PYTEST_INI}"
    cfg = configparser.ConfigParser()
    cfg.read(PYTEST_INI)
    raw_markers = cfg["pytest"]["markers"]
    declared = {
        line.split(":", 1)[0].strip()
        for line in raw_markers.splitlines()
        if line.strip() and ":" in line
    }
    assert declared == {"unit", "integration", "tdd_red"}, (
        f"pytest.ini classifier markers mismatch — got {declared}"
    )


@pytest.mark.unit
def test_pytest_ini_addopts_excludes_tdd_red():
    """Default pytest invocation must skip tdd_red tests."""
    cfg = configparser.ConfigParser()
    cfg.read(PYTEST_INI)
    addopts = cfg["pytest"]["addopts"]
    assert "not tdd_red" in addopts, (
        f"pytest.ini addopts must exclude tdd_red — got {addopts!r}"
    )


@pytest.mark.unit
def test_pytest_ini_strict_markers_enabled():
    """`--strict-markers` must be on so unregistered marks become errors."""
    cfg = configparser.ConfigParser()
    cfg.read(PYTEST_INI)
    addopts = cfg["pytest"]["addopts"]
    assert "--strict-markers" in addopts, (
        f"pytest.ini addopts must include --strict-markers — got {addopts!r}"
    )


# ---------------------------------------------------------------------------
# AC-1.2 — classifier behavior on synthetic input
# ---------------------------------------------------------------------------


def _write_test_file(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")


@pytest.mark.unit
def test_classifier_finds_marked_tests(tmp_path):
    """scan_file returns one record per test_* function with its classifier markers."""
    f = tmp_path / "test_sample.py"
    _write_test_file(
        f,
        """
        import pytest

        @pytest.mark.unit
        def test_alpha():
            assert True

        @pytest.mark.integration
        def test_beta(client):
            assert client is not None

        class TestGroup:
            @pytest.mark.unit
            def test_gamma(self):
                pass
        """,
    )
    scan = classify_tests.scan_file(f)
    qualnames = {(r.qualname, r.markers) for r in scan.tests}
    assert qualnames == {
        ("test_alpha", ("unit",)),
        ("test_beta", ("integration",)),
        ("TestGroup.test_gamma", ("unit",)),
    }


@pytest.mark.unit
def test_classifier_rejects_unmarked(tmp_path, capsys):
    """check() exits non-zero and prints the unmarked test's name + line."""
    f = tmp_path / "test_bad.py"
    _write_test_file(
        f,
        """
        def test_no_marker():
            assert True
        """,
    )
    rc = classify_tests.check([classify_tests.scan_file(f)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "unclassified" in out
    assert "test_no_marker" in out
    # Actionable hint to CLAUDE.md and the three valid markers.
    assert "@pytest.mark.unit" in out
    assert "@pytest.mark.integration" in out
    assert "@pytest.mark.tdd_red" in out


@pytest.mark.unit
def test_classifier_rejects_double_marked(tmp_path, capsys):
    """A test with two classifier markers exits non-zero with a double-marked error."""
    f = tmp_path / "test_double.py"
    _write_test_file(
        f,
        """
        import pytest

        @pytest.mark.unit
        @pytest.mark.integration
        def test_two_marks():
            assert True
        """,
    )
    rc = classify_tests.check([classify_tests.scan_file(f)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "double-marked" in out
    assert "test_two_marks" in out
    assert "unit" in out and "integration" in out


@pytest.mark.unit
def test_classifier_accepts_tdd_red(tmp_path, capsys):
    """A tdd_red marker is a valid classifier — check() exits 0."""
    f = tmp_path / "test_red.py"
    _write_test_file(
        f,
        """
        import pytest

        @pytest.mark.tdd_red
        def test_not_yet_implemented():
            assert False  # impl not written yet
        """,
    )
    rc = classify_tests.check([classify_tests.scan_file(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "tdd_red: 1" in out


@pytest.mark.unit
def test_classifier_prints_counts(tmp_path, capsys):
    """On success, classifier prints per-layer counts."""
    f = tmp_path / "test_counts.py"
    _write_test_file(
        f,
        """
        import pytest

        @pytest.mark.unit
        def test_u1(): pass

        @pytest.mark.unit
        def test_u2(): pass

        @pytest.mark.integration
        def test_i1(client): pass

        @pytest.mark.tdd_red
        def test_r1(): pass
        """,
    )
    rc = classify_tests.check([classify_tests.scan_file(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unit: 2" in out
    assert "integration: 1" in out
    assert "tdd_red: 1" in out


@pytest.mark.unit
def test_classifier_ignores_parametrize_and_skip(tmp_path):
    """pytest.mark.parametrize/skip are not classifier markers — must not satisfy."""
    f = tmp_path / "test_paramonly.py"
    _write_test_file(
        f,
        """
        import pytest

        @pytest.mark.parametrize("x", [1, 2])
        @pytest.mark.skip(reason="wip")
        def test_only_builtins(x):
            assert True
        """,
    )
    scan = classify_tests.scan_file(f)
    assert scan.tests[0].markers == ()  # neither classifier present


@pytest.mark.unit
def test_classifier_exit_code_clean_repo(tmp_path, capsys):
    """check() against an empty FileScan list exits 0 with zero counts."""
    rc = classify_tests.check([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 tests classified" in out


# ---------------------------------------------------------------------------
# AC-1.3 — REPORT mode (PF-Q1 sample generation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_report_mode_writes_sample_to_default_path(tmp_path, monkeypatch):
    """--report writes a markdown file at the provided path."""
    # Build a fake tests dir with one unit + one integration file.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write_test_file(
        tests_dir / "test_unit_example.py",
        """
        def test_pure():
            assert True
        """,
    )
    _write_test_file(
        tests_dir / "test_integration_example.py",
        """
        from fastapi.testclient import TestClient

        def test_via_client(client):
            assert client is not None
        """,
    )
    report_path = tmp_path / "report.md"
    rc = classify_tests.main(
        ["--report", str(report_path), "--tests-dir", str(tests_dir)]
    )
    assert rc == 0
    assert report_path.exists()
    body = report_path.read_text(encoding="utf-8")
    assert "Quality v1 — PF-Q1 classifier report" in body
    assert "test_unit_example.py" in body
    assert "test_integration_example.py" in body


@pytest.mark.unit
def test_report_mode_lists_per_file_distribution(tmp_path):
    """Report contains a per-file table with unit/integration columns."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write_test_file(
        tests_dir / "test_mixed.py",
        """
        from fastapi.testclient import TestClient

        def test_a():
            assert True

        def test_b(client):
            assert client is not None
        """,
    )
    report_path = tmp_path / "r.md"
    classify_tests.main(
        ["--report", str(report_path), "--tests-dir", str(tests_dir)]
    )
    body = report_path.read_text(encoding="utf-8")
    # The file imports TestClient, so the heuristic suggests integration for
    # every test in the file (suggested = integration when TestClient is imported).
    assert "test_mixed.py" in body
    assert "Distribution" in body
    assert "Per-file summary" in body


@pytest.mark.unit
def test_report_mode_suggests_integration_for_client_fixture(tmp_path):
    """A test taking the ``client`` fixture is suggested integration even without TestClient import."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_client_only.py"
    _write_test_file(
        f,
        """
        def test_via_client(client):
            assert client is not None
        """,
    )
    scan = classify_tests.scan_file(f)
    assert scan.tests[0].suggested_tier == "integration"


@pytest.mark.unit
def test_report_mode_suggests_unit_for_pure_test(tmp_path):
    """A pure-Python test (no client, no TestClient import) is suggested unit."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_pure.py"
    _write_test_file(
        f,
        """
        def test_math():
            assert 2 + 2 == 4
        """,
    )
    scan = classify_tests.scan_file(f)
    assert scan.tests[0].suggested_tier == "unit"


# ---------------------------------------------------------------------------
# AC-1.4 / AC-1.5 — End-to-end via subprocess: default run excludes tdd_red,
# unit and integration partitions are disjoint.
# ---------------------------------------------------------------------------


def _run_pytest(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Invoke pytest as a subprocess against ``cwd``."""
    env = os.environ.copy()
    # Avoid pytest discovering OUR test in the child run.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def _scaffold_sample_suite(root: Path) -> None:
    """Build a self-contained pytest project with the three markers."""
    (root / "pytest.ini").write_text(
        textwrap.dedent(
            """
            [pytest]
            markers =
                unit: Pure unit.
                integration: Stacked.
                tdd_red: Red.
            addopts = --strict-markers -m "not tdd_red"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text("", encoding="utf-8")
    _write_test_file(
        tests / "test_unit_sample.py",
        """
        import pytest

        @pytest.mark.unit
        def test_u1():
            assert True
        """,
    )
    _write_test_file(
        tests / "test_integration_sample.py",
        """
        import pytest

        @pytest.mark.integration
        def test_i1():
            assert True
        """,
    )
    _write_test_file(
        tests / "test_red_sample.py",
        """
        import pytest

        @pytest.mark.tdd_red
        def test_r1():
            assert False, "deliberately red — impl not written"
        """,
    )


@pytest.mark.unit
def test_default_run_excludes_tdd_red(tmp_path):
    """`pytest` (no args) must not run any @pytest.mark.tdd_red tests — AC-1.4."""
    _scaffold_sample_suite(tmp_path)
    result = _run_pytest(["-v"], cwd=tmp_path)
    assert result.returncode == 0, (
        f"default run should pass (tdd_red excluded). stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "test_u1" in result.stdout
    assert "test_i1" in result.stdout
    assert "test_r1" not in result.stdout, (
        "default run leaked a tdd_red test"
    )


@pytest.mark.unit
def test_unit_and_integration_partitions_disjoint(tmp_path):
    """`pytest -m unit` and `pytest -m integration` produce non-overlapping sets — AC-1.5."""
    _scaffold_sample_suite(tmp_path)
    unit_only = _run_pytest(["-m", "unit", "-v", "--collect-only", "-q"], cwd=tmp_path)
    integ_only = _run_pytest(
        ["-m", "integration", "-v", "--collect-only", "-q"], cwd=tmp_path
    )
    assert unit_only.returncode == 0, unit_only.stdout + unit_only.stderr
    assert integ_only.returncode == 0, integ_only.stdout + integ_only.stderr
    assert "test_u1" in unit_only.stdout
    assert "test_i1" not in unit_only.stdout
    assert "test_i1" in integ_only.stdout
    assert "test_u1" not in integ_only.stdout


@pytest.mark.unit
def test_strict_markers_rejects_unregistered(tmp_path):
    """`--strict-markers` is enforced: an unregistered marker fails the run."""
    _scaffold_sample_suite(tmp_path)
    _write_test_file(
        tmp_path / "tests" / "test_bad_mark.py",
        """
        import pytest

        @pytest.mark.bogus_unregistered
        def test_z():
            assert True
        """,
    )
    # Pass `-c` + `--strict-markers` explicitly so the test doesn't depend on
    # pytest config discovery (which behaves differently when pytest-cov is
    # loaded in the parent process — observed in CI vs local). The intent of
    # this test is verifying the strict-markers behavior, not pytest's config
    # search algorithm.
    result = _run_pytest(
        [
            "-c", str(tmp_path / "pytest.ini"),
            "--strict-markers",
            "-p", "no:cacheprovider",
            "tests/test_bad_mark.py",
            "-v",
        ],
        cwd=tmp_path,
    )
    assert result.returncode != 0, (
        f"pytest should reject the unregistered marker.\n"
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )
    # pytest prints the offending marker name on strict-markers failure.
    combined = result.stdout + result.stderr
    assert "bogus_unregistered" in combined
