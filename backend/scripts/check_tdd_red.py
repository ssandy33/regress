"""Quality v1 — ``tdd_red`` PR merge gate (issue #269).

Scans the set of ``.py`` files added or changed in a PR for any surviving
``tdd_red`` marker references and blocks the merge if any are found.

Why a diff-based grep (not ``pytest --collect-only -m tdd_red``)?

    A ``@pytest.mark.tdd_red`` decorator combined with an outer
    ``@pytest.mark.skip`` would NOT appear in a ``--collect-only -m tdd_red``
    listing — pytest filters by marker AFTER honouring skip — but the marker
    is still present in source. A literal grep over PR-changed ``.py`` files
    is unambiguous, fast, deterministic, and easy to reproduce locally.

The three patterns we flag (locked by the Wave 2 V1 Contract Freeze):

1. ``@pytest.mark.tdd_red``            — bare/called decorator form.
2. ``pytestmark = pytest.mark.tdd_red`` — module-scope single mark.
3. ``pytestmark = [pytest.mark.tdd_red`` — module-scope list form (open
   bracket; the rest of the list is irrelevant to detection).

Known limitation (PRD #261 R-1 accepted risk):

    ``import pytest as pt; @pt.mark.tdd_red`` slips past the literal grep.
    Aliased ``pytest`` imports are not a realistic pattern in this codebase;
    the gate optimises for zero false-negatives on the realistic cases over
    perfect coverage of pathological ones.

Two entry modes:

    python -m scripts.check_tdd_red --diff-base <ref>
        CI mode. Runs ``git diff --name-only <ref>...HEAD -- '*.py'``
        and scans each changed/added ``.py`` for the three patterns.

    python -m scripts.check_tdd_red --files FILE [FILE ...]
        Test mode. Scans the explicit list (no git invocation). Used by
        the unit tests with ``tmp_path`` fixtures.

Exit codes:

    0  no ``tdd_red`` marker found in any scanned file.
    1  at least one marker found — file:line listing printed to stderr.

The script is intentionally pytest + stdlib only; no third-party deps.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked patterns (Wave 2 V1 Contract Freeze)
# ---------------------------------------------------------------------------
#
# Each pattern is anchored at the start of a logical line (leading whitespace
# permitted) so the trivial false-positive of a quoted string somewhere in a
# docstring containing the literal ``@pytest.mark.tdd_red`` does NOT trigger
# the gate. A real decorator or real module-scope ``pytestmark`` always lives
# at column 0 after stripping leading whitespace.
#
# Trade-off (documented in CTO plan §"Edge Cases & Risks" #1):
#   - A code comment whose FIRST non-whitespace token is the literal
#     ``@pytest.mark.tdd_red`` (e.g. ``    # @pytest.mark.tdd_red``) is
#     conservatively flagged. The remediation is trivial — delete or
#     reword the comment. We accept that false positive over the
#     false-negative risk of letting a sneaky real marker through.

_DECORATOR_RE = re.compile(r"^\s*@pytest\.mark\.tdd_red\b")
_PYTESTMARK_SINGLE_RE = re.compile(r"^\s*pytestmark\s*=\s*pytest\.mark\.tdd_red\b")
_PYTESTMARK_LIST_RE = re.compile(r"^\s*pytestmark\s*=\s*\[\s*pytest\.mark\.tdd_red\b")

# Public for the unit tests — the canonical (label, regex) pairs in scan order.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("@pytest.mark.tdd_red", _DECORATOR_RE),
    ("pytestmark = pytest.mark.tdd_red", _PYTESTMARK_SINGLE_RE),
    ("pytestmark = [pytest.mark.tdd_red", _PYTESTMARK_LIST_RE),
)

# The pointer string we surface in error messages so a contributor knows
# where to read about the marker discipline.
CLAUDE_MD_POINTER = "see CLAUDE.md ## Testing Requirements"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Offense:
    """One flagged occurrence in one file."""

    file: Path
    lineno: int
    pattern_label: str
    line_text: str  # raw line for diagnostics (stripped of trailing newline)

    def format(self) -> str:
        """Render as ``<file>:<lineno>: tdd_red marker found (<pattern>) — ...``."""
        return (
            f"{self.file}:{self.lineno}: tdd_red marker found "
            f"({self.pattern_label}) — remove before merge "
            f"({CLAUDE_MD_POINTER})."
        )


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


def scan_file(path: Path) -> list[Offense]:
    """Scan one ``.py`` file for tdd_red markers; return all offences.

    Returns an empty list on:
      - missing files (the diff listed a file that's been deleted),
      - non-``.py`` paths (defensive — the caller should filter),
      - files that fail to decode as UTF-8 (unexpected for a Python source
        tree but handled gracefully).
    """
    if path.suffix != ".py":
        return []
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning(
            "tdd_red_gate: failed to read %s — skipping",
            path,
            extra={"event": "tdd_red_gate.read_error", "file": str(path)},
        )
        return []

    offences: list[Offense] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS:
            if pattern.search(line):
                offences.append(
                    Offense(
                        file=path,
                        lineno=lineno,
                        pattern_label=label,
                        line_text=line.rstrip(),
                    )
                )
                # Only flag once per line even if a contrived line matched
                # multiple patterns — the first label is informative enough.
                break
    return offences


def scan_files(paths: list[Path]) -> list[Offense]:
    """Scan many ``.py`` files; return offences in input order then line order."""
    offences: list[Offense] = []
    for path in paths:
        offences.extend(scan_file(path))
    return offences


# ---------------------------------------------------------------------------
# Git diff enumeration
# ---------------------------------------------------------------------------


def _changed_py_files(diff_base: str, repo_root: Path) -> list[Path]:
    """Return the ``.py`` files changed between ``diff_base`` and ``HEAD``.

    Uses ``git diff --name-only --diff-filter=AM <base>...HEAD -- '*.py'`` so
    only **A**dded and **M**odified files are scanned (deletions are
    irrelevant — they can't contain a surviving marker).

    The three-dot form (``<base>...HEAD``) gives the diff from the merge-base
    of <base> and HEAD to HEAD — i.e. only changes introduced on the feature
    branch since it diverged. That's the semantic the PR gate wants.
    """
    cmd = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=AM",
        f"{diff_base}...HEAD",
        "--",
        "*.py",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        # Generic message; never surface raw exception text.
        raise SystemExit("tdd_red_gate: git not available on PATH") from None
    except subprocess.CalledProcessError:
        raise SystemExit(
            f"tdd_red_gate: git diff failed for base {diff_base!r}"
        ) from None

    paths: list[Path] = []
    for raw in result.stdout.splitlines():
        name = raw.strip()
        if not name:
            continue
        paths.append((repo_root / name).resolve())
    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the repository root relative to this script (``backend/scripts/``)."""
    return Path(__file__).resolve().parent.parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_tdd_red",
        description=(
            "PR merge gate: fail if any @pytest.mark.tdd_red or "
            "module-scope pytestmark = pytest.mark.tdd_red marker survives "
            "in the PR's changed .py files."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--diff-base",
        "--base",
        dest="diff_base",
        metavar="REF",
        help=(
            "Git ref or SHA to diff against (typically "
            "${{ github.event.pull_request.base.sha }} in CI, or "
            "origin/main locally). Scans every .py file added or modified "
            "between <REF> and HEAD."
        ),
    )
    mode.add_argument(
        "--files",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="Explicit list of .py files to scan (test mode; bypasses git).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Override the repository root (default: inferred from this "
            "script's location). Used by unit tests."
        ),
    )
    return parser


def _print_offences(offences: list[Offense]) -> None:
    """Print one error line per offence to stderr."""
    for o in offences:
        print(o.format(), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logger.info(
        "tdd_red_gate starting",
        extra={
            "event": "tdd_red_gate.start",
            "mode": "diff" if args.diff_base else "files",
        },
    )

    if args.files is not None:
        paths = [p.resolve() for p in args.files]
    else:
        repo_root = (args.repo_root or _repo_root()).resolve()
        paths = _changed_py_files(args.diff_base, repo_root)

    offences = scan_files(paths)

    logger.info(
        "tdd_red_gate complete",
        extra={
            "event": "tdd_red_gate.complete",
            "files_scanned": len(paths),
            "offences": len(offences),
        },
    )

    if offences:
        _print_offences(offences)
        print(
            f"tdd_red_gate: FAIL — {len(offences)} marker(s) found in "
            f"{len({o.file for o in offences})} file(s). "
            "A Red test must be deleted or converted to passing before merge.",
            file=sys.stderr,
        )
        return 1

    print(
        f"tdd_red_gate: OK — scanned {len(paths)} changed .py file(s); "
        "no tdd_red markers found."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
