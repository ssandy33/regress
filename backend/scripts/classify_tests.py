"""Quality v1 — pytest marker classifier (issue #265).

Walks ``backend/tests/`` and enforces the test-pyramid partition agreed
in Quality v1 PRD #261:

- Every ``test_*`` function MUST carry exactly one of:
    * ``@pytest.mark.unit``        — pure-Python, no app, no TestClient, no DB.
    * ``@pytest.mark.integration`` — FastAPI TestClient + in-memory SQLite + routers.
    * ``@pytest.mark.tdd_red``     — deliberately failing Red test (skipped by default).
- ``pytest.mark.parametrize`` / ``pytest.mark.skip`` are NOT classifiers
  and are ignored by this script.

Two modes:

    python -m scripts.classify_tests              # CHECK mode (default)
    python -m scripts.classify_tests --check      # explicit CHECK mode
    python -m scripts.classify_tests --report PATH  # write a heuristic report
                                                    # of suggested classifications
                                                    # (humans apply tags by hand)

CHECK mode exit codes:
    0  every test in ``backend/tests/`` carries exactly one classifier marker.
    1  one or more tests are unclassified or double-classified — details printed.

REPORT mode never modifies any test file. It is a read-only advisory pass:
it scans imports + fixture usage with the heuristics below and writes
``markdown`` summarising the suggested tier per test. Humans then add
the actual ``@pytest.mark.<tier>`` decorators by hand (Wave 1 issue
#265's PF-Q1 sample + Wave 2's full tagging pass).

Heuristics (REPORT mode only — never decides for CHECK mode):

- A test is suggested **integration** when ANY of:
    * The file imports ``fastapi.testclient.TestClient`` directly.
    * A test function takes the ``client`` fixture parameter (the
      conftest-provided TestClient) — even transitively through another
      fixture that consumes ``client``.
    * The file imports ``app.main.app`` for direct mounting.
- Otherwise the test is suggested **unit**.

This is deliberately conservative: tests that drive in-memory SQLite
*without* the FastAPI app (e.g. ``test_rules_config.py``'s ``db`` fixture
that builds its own engine) stay **unit** because the marker definition
says integration = full backend stack (TestClient + routers + services + ORM).

The classifier is intentionally pytest + stdlib only; no third-party deps.
"""

from __future__ import annotations

import argparse
import ast
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# The three classifier markers. Order is the canonical report order.
CLASSIFIER_MARKERS: tuple[str, ...] = ("unit", "integration", "tdd_red")

# Markers we ignore (pytest built-ins or non-classifier marks).
NON_CLASSIFIER_MARKERS: frozenset[str] = frozenset(
    {"parametrize", "skip", "skipif", "xfail", "usefixtures", "filterwarnings"}
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestRecord:
    """A single discovered ``test_*`` function with its classifier markers."""

    file: Path
    qualname: str  # e.g. "TestCanonicalShape.test_returns_four_paths"
    lineno: int
    markers: tuple[str, ...]  # only classifier markers, in source order
    suggested_tier: str  # heuristic suggestion for REPORT mode


@dataclass
class FileScan:
    """Result of scanning one test_*.py file."""

    path: Path
    has_testclient_import: bool = False
    has_app_main_import: bool = False
    fixtures_using_client: set[str] = field(default_factory=set)
    tests: list[TestRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _decorator_marker_name(node: ast.expr) -> str | None:
    """Return the marker name for a ``@pytest.mark.<name>`` decorator, else None.

    Handles both bare (``@pytest.mark.unit``) and called
    (``@pytest.mark.parametrize(...)``) forms.
    """
    # The called form: ``@pytest.mark.parametrize(...)`` -> Call(func=Attribute(...))
    target = node.func if isinstance(node, ast.Call) else node
    if not isinstance(target, ast.Attribute):
        return None
    # We want ``pytest.mark.<name>`` shape: Attribute(value=Attribute(value=Name('pytest'), attr='mark'), attr='<name>')
    parent = target.value
    if not isinstance(parent, ast.Attribute):
        return None
    if parent.attr != "mark":
        return None
    grandparent = parent.value
    if not isinstance(grandparent, ast.Name) or grandparent.id != "pytest":
        return None
    return target.attr


def _classifier_markers(decorators: list[ast.expr]) -> list[str]:
    """Return the classifier markers (in source order) from a decorator list."""
    out: list[str] = []
    for deco in decorators:
        name = _decorator_marker_name(deco)
        if name in CLASSIFIER_MARKERS:
            out.append(name)
    return out


def _imports_testclient(tree: ast.Module) -> bool:
    """True iff the module imports ``fastapi.testclient.TestClient``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "fastapi.testclient":
                if any(alias.name == "TestClient" for alias in node.names):
                    return True
    return False


def _imports_app_main(tree: ast.Module) -> bool:
    """True iff the module imports ``app.main`` (the FastAPI app object)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in {"app.main", "main"}:
                return True
        if isinstance(node, ast.Import):
            if any(alias.name in {"app.main"} for alias in node.names):
                return True
    return False


def _fixture_consumes_client(func: ast.FunctionDef, known_client_fixtures: set[str]) -> bool:
    """True iff this fixture takes a parameter named ``client`` or a known transitive."""
    for arg in func.args.args:
        if arg.arg in known_client_fixtures:
            return True
    return False


def _is_pytest_fixture(decorators: list[ast.expr]) -> bool:
    """True iff any decorator looks like ``@pytest.fixture`` (bare or called)."""
    for deco in decorators:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Attribute):
            if target.attr == "fixture":
                parent = target.value
                if isinstance(parent, ast.Name) and parent.id == "pytest":
                    return True
    return False


def _walk_test_functions(tree: ast.Module):
    """Yield ``(qualname, FunctionDef)`` pairs for every ``test_*`` def.

    Recurses into top-level classes (``class Test...:``) so class-scoped
    test methods are surfaced with their ``ClassName.method`` qualname.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test_"):
                        yield f"{node.name}.{sub.name}", sub


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


def scan_file(path: Path) -> FileScan:
    """Parse ``path`` and return a :class:`FileScan` describing every test in it.

    Never raises on syntactically broken files — broken files surface as a
    ``FileScan`` with zero tests and the broken-file path so the caller can
    surface them in CHECK mode.
    """
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        logger.warning(
            "classify_tests: failed to parse %s — skipping",
            path,
            extra={"event": "classify.parse_error", "file": str(path)},
        )
        return FileScan(path=path)

    scan = FileScan(path=path)
    scan.has_testclient_import = _imports_testclient(tree)
    scan.has_app_main_import = _imports_app_main(tree)

    # First pass: discover ``client``-consuming fixtures so we know that a
    # test taking that fixture is effectively integration.
    known_client_fixtures: set[str] = {"client"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if _is_pytest_fixture(node.decorator_list):
                if _fixture_consumes_client(node, known_client_fixtures):
                    known_client_fixtures.add(node.name)
    scan.fixtures_using_client = known_client_fixtures - {"client"}

    # Second pass: collect every test_* with its classifier markers.
    for qualname, func in _walk_test_functions(tree):
        markers = tuple(_classifier_markers(func.decorator_list))
        uses_client = any(
            arg.arg in known_client_fixtures for arg in func.args.args
        )
        if scan.has_testclient_import or scan.has_app_main_import or uses_client:
            suggested = "integration"
        else:
            suggested = "unit"
        scan.tests.append(
            TestRecord(
                file=path,
                qualname=qualname,
                lineno=func.lineno,
                markers=markers,
                suggested_tier=suggested,
            )
        )
    return scan


def scan_directory(tests_dir: Path) -> list[FileScan]:
    """Scan every ``test_*.py`` file in ``tests_dir`` (non-recursive)."""
    if not tests_dir.is_dir():
        raise SystemExit(
            f"classify_tests: tests directory not found: {tests_dir}"
        )
    return [
        scan_file(p)
        for p in sorted(tests_dir.glob("test_*.py"))
    ]


# ---------------------------------------------------------------------------
# CHECK mode
# ---------------------------------------------------------------------------


def check(scans: list[FileScan]) -> int:
    """Enforce: every test has exactly one classifier marker.

    Returns process-style exit code: 0 = clean, 1 = violations.
    """
    unclassified: list[TestRecord] = []
    double_classified: list[TestRecord] = []
    counts: Counter[str] = Counter()

    for scan in scans:
        for record in scan.tests:
            if len(record.markers) == 0:
                unclassified.append(record)
            elif len(record.markers) > 1:
                double_classified.append(record)
            else:
                counts[record.markers[0]] += 1

    if unclassified or double_classified:
        print("classify_tests: FAIL — unclassified or double-classified tests:")
        for r in unclassified:
            print(
                f"  [unclassified] {r.file}:{r.lineno} {r.qualname} "
                "— no classifier marker. Add one of "
                "@pytest.mark.unit / @pytest.mark.integration / @pytest.mark.tdd_red "
                "(see CLAUDE.md Testing Pyramid section)."
            )
        for r in double_classified:
            print(
                f"  [double-marked] {r.file}:{r.lineno} {r.qualname} "
                f"— has {len(r.markers)} classifier markers ({', '.join(r.markers)}); "
                "exactly one is required."
            )
        return 1

    parts = ", ".join(f"{m}: {counts.get(m, 0)}" for m in CLASSIFIER_MARKERS)
    total = sum(counts.values())
    print(f"classify_tests: OK — {total} tests classified ({parts}).")
    return 0


# ---------------------------------------------------------------------------
# REPORT mode
# ---------------------------------------------------------------------------


def write_report(scans: list[FileScan], out_path: Path) -> None:
    """Write a human-reviewable markdown report of suggested classifications.

    The report is the PF-Q1 deliverable for issue #265 AC-1.3: humans
    use it to apply markers by hand to the sample (and, in Wave 2, the
    full suite).
    """
    suggested_counts: Counter[str] = Counter()
    per_file_counts: list[tuple[Path, Counter[str], FileScan]] = []
    for scan in scans:
        c: Counter[str] = Counter()
        for record in scan.tests:
            c[record.suggested_tier] += 1
            suggested_counts[record.suggested_tier] += 1
        per_file_counts.append((scan.path, c, scan))

    lines: list[str] = []
    lines.append("# Quality v1 — PF-Q1 classifier report")
    lines.append("")
    lines.append(
        "Generated by `backend/scripts/classify_tests.py --report`. "
        "Heuristic suggestions only — humans apply the actual "
        "`@pytest.mark.<tier>` decorators per Quality v1 (#261, #265)."
    )
    lines.append("")
    lines.append("## Heuristics")
    lines.append("")
    lines.append(
        "- **integration** if the file imports `fastapi.testclient.TestClient`, "
        "imports `app.main`, or a test takes the `client` fixture "
        "(or any fixture transitively consuming `client`)."
    )
    lines.append("- **unit** otherwise.")
    lines.append("")
    lines.append("## Distribution")
    lines.append("")
    total = sum(suggested_counts.values())
    lines.append(f"- Total tests scanned: **{total}**")
    for tier in ("unit", "integration"):
        lines.append(f"- Suggested **{tier}**: {suggested_counts.get(tier, 0)}")
    lines.append("")
    lines.append("## Per-file summary")
    lines.append("")
    lines.append("| File | unit | integration | TestClient import | app.main import |")
    lines.append("|---|---:|---:|:---:|:---:|")
    for path, c, scan in per_file_counts:
        lines.append(
            "| `{name}` | {u} | {i} | {tc} | {am} |".format(
                name=path.name,
                u=c.get("unit", 0),
                i=c.get("integration", 0),
                tc="yes" if scan.has_testclient_import else "no",
                am="yes" if scan.has_app_main_import else "no",
            )
        )
    lines.append("")
    lines.append("## PF-Q1 hand-marked sample")
    lines.append("")
    lines.append(
        "Issue #265 AC-1.3 calls for 5 unit + 3 integration tests "
        "to be hand-marked across these four files:"
    )
    lines.append("")
    pf_q1_files = {
        "test_recovery_engine.py",
        "test_rules_config.py",
        "test_integration_dashboard.py",
        "test_integration_settings.py",
    }
    for path, _c, scan in per_file_counts:
        if path.name not in pf_q1_files:
            continue
        lines.append(f"### `{path.name}`")
        lines.append("")
        for r in scan.tests[:8]:
            marker_str = (
                ", ".join(f"`{m}`" for m in r.markers) if r.markers else "_none_"
            )
            lines.append(
                f"- L{r.lineno} `{r.qualname}` — suggested **{r.suggested_tier}**, applied: {marker_str}"
            )
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(
        "wrote classifier report",
        extra={
            "event": "classify.report.written",
            "path": str(out_path),
            "total_tests": total,
            "suggested_unit": suggested_counts.get("unit", 0),
            "suggested_integration": suggested_counts.get("integration", 0),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_tests_dir() -> Path:
    """Locate ``backend/tests/`` relative to this script."""
    return Path(__file__).resolve().parent.parent / "tests"


def _default_report_path() -> Path:
    """PF-Q1 sample path: lives alongside the design specs (untracked)."""
    return (
        Path(__file__).resolve().parent.parent
        / "design-specs"
        / "quality-v1-pf-q1-sample.md"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="classify_tests",
        description=(
            "Enforce the Quality v1 pytest-marker partition "
            "(unit / integration / tdd_red). Default mode is --check."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify every test has exactly one classifier marker (default).",
    )
    parser.add_argument(
        "--report",
        nargs="?",
        const=str(_default_report_path()),
        default=None,
        metavar="PATH",
        help=(
            "Write a heuristic suggested-classification report to PATH "
            "(default: backend/design-specs/quality-v1-pf-q1-sample.md). "
            "Read-only — never modifies any test file."
        ),
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=_default_tests_dir(),
        help="Override the tests directory (default: backend/tests/).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    scans = scan_directory(args.tests_dir)

    if args.report is not None:
        write_report(scans, Path(args.report))
        print(f"classify_tests: report written to {args.report}")
        # Report mode does not enforce — it is read-only.
        return 0

    # Default: --check
    return check(scans)


if __name__ == "__main__":
    sys.exit(main())
