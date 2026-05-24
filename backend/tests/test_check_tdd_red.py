"""Tests for ``backend/scripts/check_tdd_red.py`` — the tdd_red PR merge gate.

Covers the AC test list in issue #269 (Quality v1 Wave 2):

| AC    | Test                                                             |
|-------|------------------------------------------------------------------|
| 5.3   | test_flags_decorator_form                                        |
| 5.3   | test_flags_module_pytestmark_single                              |
| 5.3   | test_flags_module_pytestmark_list                                |
| 5.3   | test_clean_diff_passes                                           |
| 5.3   | test_ignores_non_py_files                                        |
| 5.6   | test_error_message_includes_claude_md_pointer                    |
| 5.6   | test_multiple_offenders_lists_all                                |
| 5.3   | test_removed_marker_does_not_flag                                |
| 5.3   | test_marker_in_docstring_string_literal_is_not_flagged           |
| 5.3   | test_indented_decorator_inside_class_is_flagged                  |
| 5.3   | test_files_mode_scans_explicit_paths                             |
| 5.3   | test_diff_mode_invokes_git_and_scans_results                     |

The gate is a pure-function classifier — no FastAPI app, no DB, no network.
Every test here is marked ``@pytest.mark.unit`` per the Wave 1 pyramid.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts import check_tdd_red


REPO_BACKEND = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = REPO_BACKEND.parent  # repo root


# The literal marker tokens we test against. Assembled at runtime from
# substrings so the gate cannot flag THIS file (the gate's own test file
# must stay clean — see Edge Cases & Risks #5 in the CTO plan).
_MARK = "pytest.mark." + "tdd_red"
_DEC = "@" + _MARK
_PYTESTMARK_SINGLE = "pytestmark = " + _MARK
_PYTESTMARK_LIST = "pytestmark = [" + _MARK + ", pytest.mark.unit]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# AC-5.3 — scan_file detects each of the three locked patterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_flags_decorator_form(tmp_path: Path) -> None:
    """The decorator form is flagged."""
    f = _write(
        tmp_path / "test_red_decorator.py",
        f"""
        import pytest

        {_DEC}
        def test_foo():
            assert False
        """,
    )

    offences = check_tdd_red.scan_file(f)

    assert len(offences) == 1
    assert offences[0].file == f
    assert offences[0].lineno == 3  # decorator is on line 3 after dedent
    assert offences[0].pattern_label == _DEC


@pytest.mark.unit
def test_flags_module_pytestmark_single(tmp_path: Path) -> None:
    """Module-scope single ``pytestmark =`` assignment is flagged."""
    f = _write(
        tmp_path / "test_red_module_mark.py",
        f"""
        import pytest

        {_PYTESTMARK_SINGLE}


        def test_foo():
            assert False
        """,
    )

    offences = check_tdd_red.scan_file(f)

    assert len(offences) == 1
    assert offences[0].lineno == 3
    assert offences[0].pattern_label == "pytestmark = " + "pytest.mark." + "tdd_red"


@pytest.mark.unit
def test_flags_module_pytestmark_list(tmp_path: Path) -> None:
    """Module-scope list-form ``pytestmark = [...]`` is flagged."""
    f = _write(
        tmp_path / "test_red_module_list.py",
        f"""
        import pytest

        {_PYTESTMARK_LIST}


        def test_foo():
            assert False
        """,
    )

    offences = check_tdd_red.scan_file(f)

    assert len(offences) == 1
    assert offences[0].lineno == 3
    assert offences[0].pattern_label == "pytestmark = [" + "pytest.mark." + "tdd_red"


@pytest.mark.unit
def test_clean_diff_passes(tmp_path: Path) -> None:
    """A file with no tdd_red references produces zero offences."""
    f = _write(
        tmp_path / "test_clean.py",
        """
        import pytest

        @pytest.mark.unit
        def test_ok():
            assert 1 + 1 == 2
        """,
    )

    offences = check_tdd_red.scan_file(f)

    assert offences == []


@pytest.mark.unit
def test_ignores_non_py_files(tmp_path: Path) -> None:
    """A non-``.py`` file containing the literal marker is NOT scanned."""
    f = _write(
        tmp_path / "README.md",
        f"""
        Don't forget to remove ``{_DEC}`` before merging.
        Also: {_PYTESTMARK_SINGLE}.
        """,
    )

    offences = check_tdd_red.scan_file(f)

    assert offences == []


# ---------------------------------------------------------------------------
# AC-5.6 — error messages are actionable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_message_includes_claude_md_pointer(tmp_path: Path) -> None:
    """Each formatted offence points at the CLAUDE.md section for context."""
    f = _write(
        tmp_path / "test_red.py",
        f"""
        import pytest

        {_DEC}
        def test_foo():
            pass
        """,
    )

    offences = check_tdd_red.scan_file(f)
    msg = offences[0].format()

    assert "CLAUDE.md" in msg
    assert "Testing Requirements" in msg
    assert str(f) in msg
    assert ":3:" in msg  # file:line in the message


@pytest.mark.unit
def test_multiple_offenders_lists_all(tmp_path: Path) -> None:
    """``scan_files`` reports every offence across every file."""
    f1 = _write(
        tmp_path / "test_one.py",
        f"""
        import pytest

        {_DEC}
        def test_one():
            pass
        """,
    )
    f2 = _write(
        tmp_path / "test_two.py",
        f"""
        import pytest

        {_PYTESTMARK_SINGLE}


        def test_two():
            pass
        """,
    )

    offences = check_tdd_red.scan_files([f1, f2])

    assert len(offences) == 2
    files_seen = {o.file for o in offences}
    assert files_seen == {f1, f2}


# ---------------------------------------------------------------------------
# AC-5.3 (edge cases)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_removed_marker_does_not_flag(tmp_path: Path, monkeypatch) -> None:
    """In diff mode, a marker REMOVED on the feature branch is not flagged.

    Concretely: a real git history where the previous commit had
    ``@pytest.mark.tdd_red`` and HEAD removed it. The diff-base scan
    enumerates files that were Added or Modified in HEAD relative to
    base; we then re-scan those files at HEAD. Since the marker is gone
    from HEAD, no offence is reported.
    """
    repo = tmp_path
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)

    target = repo / "backend" / "tests" / "test_red.py"
    _write(
        target,
        f"""
        import pytest

        {_DEC}
        def test_foo():
            pass
        """,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial with tdd_red"],
        cwd=repo,
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Now remove the marker on HEAD.
    _write(
        target,
        """
        import pytest

        @pytest.mark.unit
        def test_foo():
            pass
        """,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "remove tdd_red"],
        cwd=repo,
        check=True,
    )

    paths = check_tdd_red._changed_py_files(base_sha, repo)
    offences = check_tdd_red.scan_files(paths)

    # The file IS in the diff (it was modified), but its CURRENT content has
    # no marker — no offence.
    assert any(p.name == "test_red.py" for p in paths)
    assert offences == []


@pytest.mark.unit
def test_marker_in_docstring_string_literal_is_not_flagged(tmp_path: Path) -> None:
    """A docstring mentioning the literal marker (with leading non-whitespace
    text) is NOT flagged because the regex anchors at the start of a logical
    line. A real decorator always starts at column 0 of its line."""
    f = _write(
        tmp_path / "test_docstring.py",
        f'''
        """Docstring example.

        Don't put {_DEC} on merged tests.
        Also: {_PYTESTMARK_SINGLE} is wrong on main.
        """

        import pytest


        @pytest.mark.unit
        def test_ok():
            pass
        ''',
    )

    offences = check_tdd_red.scan_file(f)

    # The two mentions are inside a docstring with leading "Don't put " or
    # "Also: " — the line does NOT start with @pytest or pytestmark. Clean.
    assert offences == []


@pytest.mark.unit
def test_indented_decorator_inside_class_is_flagged(tmp_path: Path) -> None:
    """A decorator inside ``class TestFoo:`` is still flagged (leading WS allowed)."""
    f = _write(
        tmp_path / "test_class_red.py",
        f"""
        import pytest


        class TestRed:
            {_DEC}
            def test_x(self):
                pass
        """,
    )

    offences = check_tdd_red.scan_file(f)

    assert len(offences) == 1
    assert offences[0].pattern_label == _DEC


@pytest.mark.unit
def test_files_mode_scans_explicit_paths(tmp_path: Path, capsys) -> None:
    """``--files`` mode bypasses git and scans the explicit list; exits 1 on
    finding a marker."""
    f = _write(
        tmp_path / "test_explicit.py",
        f"""
        import pytest

        {_DEC}
        def test_foo():
            pass
        """,
    )

    exit_code = check_tdd_red.main(["--files", str(f)])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert str(f) in err
    assert "tdd_red marker found" in err
    assert "CLAUDE.md" in err


@pytest.mark.unit
def test_files_mode_clean_exits_zero(tmp_path: Path, capsys) -> None:
    """``--files`` mode on a clean file exits 0 with a one-line OK message."""
    f = _write(
        tmp_path / "test_clean.py",
        """
        import pytest

        @pytest.mark.unit
        def test_foo():
            assert True
        """,
    )

    exit_code = check_tdd_red.main(["--files", str(f)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OK" in out
    assert "tdd_red_gate" in out


@pytest.mark.unit
def test_diff_mode_invokes_git_and_scans_results(tmp_path: Path, capsys) -> None:
    """``--diff-base`` mode runs ``git diff`` against the supplied base SHA
    and scans whatever files come back."""
    repo = tmp_path
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)

    # Base commit: empty placeholder.
    _write(repo / "placeholder.py", "# baseline\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=repo,
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # HEAD commit: add an offending file.
    _write(
        repo / "backend" / "tests" / "test_red.py",
        f"""
        import pytest

        {_DEC}
        def test_foo():
            pass
        """,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add red"],
        cwd=repo,
        check=True,
    )

    exit_code = check_tdd_red.main(
        ["--diff-base", base_sha, "--repo-root", str(repo)]
    )

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "test_red.py" in err
    assert "tdd_red marker found" in err


@pytest.mark.unit
def test_diff_mode_clean_pr_exits_zero(tmp_path: Path, capsys) -> None:
    """A PR that touches a .py file but adds no tdd_red marker exits 0."""
    repo = tmp_path
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)

    _write(repo / "placeholder.py", "# baseline\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    _write(
        repo / "backend" / "tests" / "test_ok.py",
        """
        import pytest

        @pytest.mark.unit
        def test_ok():
            assert True
        """,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add ok"], cwd=repo, check=True)

    exit_code = check_tdd_red.main(
        ["--diff-base", base_sha, "--repo-root", str(repo)]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OK" in out


@pytest.mark.unit
def test_scan_file_handles_missing_path(tmp_path: Path) -> None:
    """A missing file (e.g. deleted on branch) yields zero offences, no raise."""
    ghost = tmp_path / "does_not_exist.py"
    assert check_tdd_red.scan_file(ghost) == []


@pytest.mark.unit
def test_scan_file_skips_non_py(tmp_path: Path) -> None:
    """A .md / .txt file passed directly is silently skipped."""
    txt = _write(
        tmp_path / "README.txt",
        _DEC + "\n",
    )
    assert check_tdd_red.scan_file(txt) == []


# ---------------------------------------------------------------------------
# CLI parser shape (catches regressions to the locked CLI surface)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_requires_exactly_one_mode(tmp_path: Path) -> None:
    """``--diff-base`` and ``--files`` are mutually exclusive and one is required."""
    parser = check_tdd_red.build_parser()

    # Neither -> SystemExit (parser error).
    with pytest.raises(SystemExit):
        parser.parse_args([])

    # Both -> SystemExit.
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--diff-base", "origin/main", "--files", str(tmp_path / "x.py")]
        )

    # --diff-base alone -> ok.
    ns = parser.parse_args(["--diff-base", "origin/main"])
    assert ns.diff_base == "origin/main"
    assert ns.files is None

    # --base alias works (the CTO plan accepted either --diff-base or --base).
    ns = parser.parse_args(["--base", "abc123"])
    assert ns.diff_base == "abc123"


@pytest.mark.unit
def test_module_runnable_as_script() -> None:
    """``python -m scripts.check_tdd_red --help`` works (CI-invocation shape)."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_tdd_red", "--help"],
        cwd=str(REPO_BACKEND),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "tdd_red" in result.stdout
    assert "--diff-base" in result.stdout
    assert "--files" in result.stdout
