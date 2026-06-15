"""Test-traceability matrix generator (test-traceability ADR, extends PRD #261).

Collects the ``@pytest.mark.ac(...)`` requirement tags across the backend test
suite and emits an AC-ID -> covering-tests mapping in two surfaces:

1. ``TEST-MATRIX.md`` (default at the repo root) — a committed, diffable
   inventory: one table of ``AC-ID | covering tests (name + layer + file)``
   plus a section listing every KNOWN AC-ID with NO coverage.
2. A GitHub Actions job summary — the same matrix written to the file named by
   ``$GITHUB_STEP_SUMMARY`` (the "test plan with results" surface).

Three modes::

    python -m scripts.gen_test_matrix              # write TEST-MATRIX.md
    python -m scripts.gen_test_matrix --check      # CI gate: exit 1 if a known
                                                   #   AC-ID has zero tests
    python -m scripts.gen_test_matrix --summary    # also append to
                                                   #   $GITHUB_STEP_SUMMARY

``--check`` and ``--summary`` compose with the default write (and with each
other). ``--check`` does NOT write ``TEST-MATRIX.md`` unless ``--write`` is
also passed, so the gate is side-effect-free in CI.

Collection strategy
-------------------

Pure-AST, mirroring ``classify_tests.py``: we parse each ``test_*.py`` file and
read the args of any ``@pytest.mark.ac(...)`` decorator. No pytest invocation,
no import of the suite — deterministic, offline, fast, and immune to a test
that fails to import. The classifier marker on the same test gives the layer.

The KNOWN-AC registry (the set of AC-IDs that MUST have coverage) is declared
in ``KNOWN_AC_IDS`` below. This is the prototype home; the ADR's Open Question 2
covers promoting it to a ``test-matrix.toml`` once a second issue adopts AC-IDs.

The generator is intentionally pytest + stdlib only; no third-party deps.
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# The classifier markers, in canonical layer order. Reused to label each test's
# tier in the matrix. Kept local (not imported) so this script stays a
# self-contained sibling of classify_tests.py.
CLASSIFIER_MARKERS: tuple[str, ...] = ("unit", "integration", "tdd_red")

# ---------------------------------------------------------------------------
# KNOWN-AC registry (ADR Decision 4 / Open Question 2)
# ---------------------------------------------------------------------------
#
# The AC-IDs the project has committed to covering. An entry here with zero
# covering tests fails ``--check``. A tagged test referencing an AC-ID NOT in
# this set is a WARNING (catches typos like "349-AC33"), not a hard failure —
# adoption is incremental per the ADR's Migration section.
#
# Prototype seed: issue #349's 13 acceptance criteria.
KNOWN_AC_IDS: dict[str, str] = {
    "349-AC1": "Archetype 1 — deep-ITM short call -> assignment risk High",
    "349-AC2": "Archetype 2 — near-the-money short call <=14 DTE -> Watch",
    "349-AC3": "Archetype 3 — OTM short call long DTE -> Low",
    "349-AC4": "Archetype 4 — covered call live mark -> BTC panel populated",
    "349-AC5": "Archetype 5 — cash-secured put 0 shares -> CC-only gate + 0-share basis",
    "349-AC6": "Archetype 6 — CC no live mark -> degraded em-dash sentinel",
    "349-AC7": "Archetype 7 — multi-share equity adjusted != broker basis -> /sh",
    "349-AC8": "Mechanism — idempotent reseed (wipe tagged + reseed)",
    "349-AC9": "Mechanism — all 7 present; non-zero exit on archetype failure",
    "349-AC10": "Mechanism — dry-run / list mode writes nothing",
    "349-AC11": "Safety — prod guard aborts before any DB write",
    "349-AC12": "Safety — prod guard is tested (APP_ENV=production raises/exits)",
    "349-AC13": "Test coverage — seed logic has unit + integration coverage per pyramid",
}

# AC-IDs that are satisfied structurally rather than by a single dedicated test
# (meta-ACs). #349-AC13 ("seed logic has unit AND integration coverage") is
# proven by the suite as a whole carrying both tiers; it is checked specially in
# ``check()`` (the suite must contain at least one unit AND one integration
# AC-tagged #349 test) rather than requiring a literal ``ac("349-AC13")`` tag.
META_AC_IDS: frozenset[str] = frozenset({"349-AC13"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestRef:
    """One AC-tagged test discovered in the suite."""

    qualname: str  # e.g. "TestFoo.test_bar" or "test_baz"
    file: str  # filename only (e.g. "test_seed_qa.py")
    layer: str  # "unit" / "integration" / "tdd_red" / "unclassified"
    ac_ids: tuple[str, ...]  # AC-IDs this test declares


@dataclass
class Matrix:
    """The collected AC -> tests mapping plus diagnostics."""

    tests: list[TestRef] = field(default_factory=list)
    # AC-ID -> list of TestRef covering it (sorted, deduped on insert).
    by_ac: dict[str, list[TestRef]] = field(default_factory=lambda: defaultdict(list))
    # AC-IDs referenced by a test but NOT in KNOWN_AC_IDS (likely typos).
    unknown_ac_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# AST collection
# ---------------------------------------------------------------------------


def _classifier_layer(decorators: list[ast.expr]) -> str:
    """Return the test's classifier tier, or 'unclassified' if none found."""
    for deco in decorators:
        name = _marker_name(deco)
        if name in CLASSIFIER_MARKERS:
            return name
    return "unclassified"


def _marker_name(node: ast.expr) -> str | None:
    """Return the ``<name>`` of a ``@pytest.mark.<name>`` decorator, else None.

    Handles both bare (``@pytest.mark.unit``) and called
    (``@pytest.mark.ac(...)``) decorator forms.
    """
    target = node.func if isinstance(node, ast.Call) else node
    if not isinstance(target, ast.Attribute):
        return None
    parent = target.value
    if not isinstance(parent, ast.Attribute) or parent.attr != "mark":
        return None
    grandparent = parent.value
    if not isinstance(grandparent, ast.Name) or grandparent.id != "pytest":
        return None
    return target.attr


def _ac_ids_from_decorators(decorators: list[ast.expr]) -> tuple[str, ...]:
    """Extract AC-IDs from every ``@pytest.mark.ac("...", "...")`` decorator.

    Only string-literal positional args are collected. A non-literal arg
    (e.g. a variable) is ignored — the convention is plain string literals so
    the matrix is statically derivable without importing the suite.
    """
    out: list[str] = []
    for deco in decorators:
        if not isinstance(deco, ast.Call):
            continue
        if _marker_name(deco) != "ac":
            continue
        for arg in deco.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(arg.value)
    return tuple(out)


def _walk_test_functions(tree: ast.Module):
    """Yield ``(qualname, decorator_list)`` for every ``test_*`` def.

    Recurses one level into ``class Test...:`` bodies so class-scoped methods
    surface as ``ClassName.method`` — same traversal as classify_tests.py.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                yield node.name, node.decorator_list
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test_"):
                        yield f"{node.name}.{sub.name}", sub.decorator_list


def scan_file(path: Path) -> list[TestRef]:
    """Parse ``path`` and return a TestRef for every AC-tagged test in it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        logger.warning(
            "gen_test_matrix: failed to parse %s — skipping",
            path,
            extra={"event": "gen_test_matrix.parse_error", "outcome": "degraded"},
        )
        return []

    refs: list[TestRef] = []
    for qualname, decorators in _walk_test_functions(tree):
        ac_ids = _ac_ids_from_decorators(decorators)
        if not ac_ids:
            continue
        refs.append(
            TestRef(
                qualname=qualname,
                file=path.name,
                layer=_classifier_layer(decorators),
                ac_ids=ac_ids,
            )
        )
    return refs


def collect(tests_dir: Path) -> Matrix:
    """Scan ``tests_dir`` and build the AC -> tests matrix."""
    if not tests_dir.is_dir():
        raise SystemExit(f"gen_test_matrix: tests directory not found: {tests_dir}")

    matrix = Matrix()
    for path in sorted(tests_dir.glob("test_*.py")):
        for ref in scan_file(path):
            matrix.tests.append(ref)
            for ac_id in ref.ac_ids:
                if ref not in matrix.by_ac[ac_id]:
                    matrix.by_ac[ac_id].append(ref)
                if ac_id not in KNOWN_AC_IDS:
                    matrix.unknown_ac_ids.add(ac_id)
    return matrix


# ---------------------------------------------------------------------------
# Coverage analysis
# ---------------------------------------------------------------------------


def _meta_ac_satisfied(ac_id: str, matrix: Matrix) -> bool:
    """Whether a meta-AC's structural requirement is met.

    Currently only ``349-AC13`` (seed logic carries BOTH unit and integration
    coverage): satisfied when the suite has >=1 unit AND >=1 integration test
    tagged with any ``349-AC*`` id.
    """
    if ac_id == "349-AC13":
        layers = {
            ref.layer
            for ref in matrix.tests
            if any(a.startswith("349-AC") for a in ref.ac_ids)
        }
        return "unit" in layers and "integration" in layers
    return False  # unknown meta-AC — treat as uncovered (fail-closed)


def uncovered_known_acs(matrix: Matrix) -> list[str]:
    """Return KNOWN AC-IDs with zero covering tests (meta-ACs checked specially)."""
    missing: list[str] = []
    for ac_id in KNOWN_AC_IDS:
        if ac_id in META_AC_IDS:
            if not _meta_ac_satisfied(ac_id, matrix):
                missing.append(ac_id)
        elif not matrix.by_ac.get(ac_id):
            missing.append(ac_id)
    return missing


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(matrix: Matrix) -> str:
    """Render the matrix as the committed/job-summary markdown document."""
    covered = sum(1 for a in KNOWN_AC_IDS if a not in uncovered_known_acs(matrix))
    total_known = len(KNOWN_AC_IDS)

    lines: list[str] = []
    lines.append("# Test traceability matrix")
    lines.append("")
    lines.append(
        "Generated by `backend/scripts/gen_test_matrix.py` from "
        "`@pytest.mark.ac(...)` tags. Do not edit by hand — regenerate with "
        "`cd backend && python -m scripts.gen_test_matrix`. "
        "Mechanism: test-traceability ADR (extends PRD #261)."
    )
    lines.append("")
    lines.append(f"- Known AC-IDs: **{total_known}**")
    lines.append(f"- Covered: **{covered}/{total_known}**")
    lines.append(f"- AC-tagged tests: **{len(matrix.tests)}**")
    lines.append("")

    lines.append("## Coverage matrix")
    lines.append("")
    lines.append("| AC-ID | Description | Covering tests (layer · file) |")
    lines.append("|---|---|---|")
    for ac_id, desc in KNOWN_AC_IDS.items():
        if ac_id in META_AC_IDS:
            ok = _meta_ac_satisfied(ac_id, matrix)
            cell = (
                "_structural: suite carries unit + integration #349 tests_"
                if ok
                else "**— NO COVERAGE —**"
            )
        else:
            refs = matrix.by_ac.get(ac_id, [])
            if refs:
                cell = "<br>".join(
                    f"`{r.qualname}` ({r.layer} · {r.file})" for r in refs
                )
            else:
                cell = "**— NO COVERAGE —**"
        lines.append(f"| `{ac_id}` | {desc} | {cell} |")
    lines.append("")

    missing = uncovered_known_acs(matrix)
    lines.append("## Known AC-IDs with NO coverage")
    lines.append("")
    if missing:
        for ac_id in missing:
            lines.append(f"- `{ac_id}` — {KNOWN_AC_IDS[ac_id]}")
    else:
        lines.append("_None — every known AC-ID has at least one covering test._")
    lines.append("")

    if matrix.unknown_ac_ids:
        lines.append("## Unknown AC-IDs referenced by tests (possible typos)")
        lines.append("")
        for ac_id in sorted(matrix.unknown_ac_ids):
            covering = matrix.by_ac.get(ac_id, [])
            who = ", ".join(f"`{r.qualname}`" for r in covering)
            lines.append(f"- `{ac_id}` — referenced by {who} but not in the registry")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output sinks
# ---------------------------------------------------------------------------


def write_matrix_file(matrix: Matrix, out_path: Path) -> None:
    """Write ``TEST-MATRIX.md`` to ``out_path``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(matrix), encoding="utf-8")
    logger.info(
        "gen_test_matrix: wrote matrix",
        extra={
            "event": "gen_test_matrix.file_written",
            "outcome": "success",
            "path": str(out_path),
        },
    )


def write_job_summary(matrix: Matrix) -> bool:
    """Append the matrix to ``$GITHUB_STEP_SUMMARY`` if that env var is set.

    Returns True if written, False if the env var is absent (local run).
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return False
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write(render_markdown(matrix))
    logger.info(
        "gen_test_matrix: wrote job summary",
        extra={"event": "gen_test_matrix.summary_written", "outcome": "success"},
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_tests_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "tests"


def _default_matrix_path() -> Path:
    """Repo-root ``TEST-MATRIX.md`` (backend/scripts/ -> backend -> repo root)."""
    return Path(__file__).resolve().parent.parent.parent / "TEST-MATRIX.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gen_test_matrix",
        description=(
            "Collect @pytest.mark.ac(...) tags into a requirement->test "
            "traceability matrix (TEST-MATRIX.md + CI job summary + coverage gate)."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Coverage gate: exit 1 if any known AC-ID has zero covering tests. "
        "Does not write TEST-MATRIX.md unless --write is also passed.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Append the matrix to $GITHUB_STEP_SUMMARY (no-op locally).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Force writing TEST-MATRIX.md (implied when neither --check nor "
        "--summary is given).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_matrix_path(),
        help="Output path for TEST-MATRIX.md (default: repo-root TEST-MATRIX.md).",
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=_default_tests_dir(),
        help="Override the tests directory (default: backend/tests/).",
    )
    return parser


def check(matrix: Matrix) -> int:
    """Coverage gate. Returns 0 if every known AC-ID is covered, else 1."""
    missing = uncovered_known_acs(matrix)
    if missing:
        print("gen_test_matrix: FAIL — known AC-IDs with zero covering tests:")
        for ac_id in missing:
            print(f"  [uncovered] {ac_id} — {KNOWN_AC_IDS[ac_id]}")
        print(
            "Add a test tagged @pytest.mark.ac(\"<AC-ID>\") (or, for a meta-AC, "
            "the required tier coverage). See the test-traceability ADR."
        )
        return 1
    if matrix.unknown_ac_ids:
        # Non-fatal: surface typos but don't block (adoption is incremental).
        print(
            "gen_test_matrix: WARN — tests reference AC-IDs not in the registry: "
            + ", ".join(sorted(matrix.unknown_ac_ids))
        )
    print(
        f"gen_test_matrix: OK — {len(KNOWN_AC_IDS)} known AC-IDs all covered "
        f"by {len(matrix.tests)} AC-tagged test(s)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    started = time.perf_counter()
    logger.info("gen_test_matrix starting", extra={"event": "gen_test_matrix.start"})

    matrix = collect(args.tests_dir)

    # Default behavior (no mode flags) is "write the file".
    should_write = args.write or not (args.check or args.summary)
    if should_write:
        write_matrix_file(matrix, args.out)
        print(f"gen_test_matrix: wrote {args.out}")

    if args.summary:
        if write_job_summary(matrix):
            print("gen_test_matrix: appended matrix to $GITHUB_STEP_SUMMARY")
        else:
            print("gen_test_matrix: $GITHUB_STEP_SUMMARY not set — skipped summary")

    exit_code = 0
    if args.check:
        exit_code = check(matrix)

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "gen_test_matrix complete",
        extra={
            "event": "gen_test_matrix.complete",
            "outcome": "failed" if exit_code else "success",
            "duration_ms": duration_ms,
        },
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
