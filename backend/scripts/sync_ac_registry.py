"""Offline sync of the issue-body-derived AC registry (ADR #356, Decision 4).

The set of "known" AC-IDs is the single source of truth for the coverage gate
in ``gen_test_matrix.py``. Per ADR #356 OQ2 the source of truth is the **issue
body** — the numbered acceptance criteria each adopted issue enumerates as a
``- [ ] **AC<n>** <description>`` checklist (the form the feature-writer emits).

To keep the gate deterministic and offline, the issue ACs are *materialized*
here into a committed registry file (``ac_registry.json``). This script is the
bridge: it calls the ``gh`` CLI (network), parses the AC checklist out of each
adopted issue's body, and writes the committed file. The ``gen_test_matrix.py``
``--check`` gate then reads that local file and never touches the network.

Usage::

    # Regenerate the committed registry from the adopted issues' bodies:
    python -m scripts.sync_ac_registry

    # Drift gate (CI / pre-commit): exit 1 if the committed file is stale:
    python -m scripts.sync_ac_registry --check

The set of adopted issues lives in ``ADOPTED_ISSUES`` below. Adoption is
incremental (mirrors PRD #261's "new tests on new issues"): an issue's ACs only
become "known" — and thus gated — once its number is added here and the file is
re-synced. The seed is #349 (the ADR's prototype vehicle).

Stdlib + the ``gh`` CLI only; no third-party deps (mirrors classify_tests.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Issues whose ACs are "known" to the coverage gate. Append a number here (and
# re-run this sync) to adopt an issue's acceptance criteria into the registry.
ADOPTED_ISSUES: tuple[int, ...] = (349,)

# The GitHub repo the `gh` CLI targets. Kept explicit so the sync is repo-pinned
# regardless of the caller's cwd / default remote.
GH_REPO: str = "ssandy33/regress"

# Matches a numbered acceptance-criterion checklist line in an issue body, e.g.
#   - [ ] **AC1 · Archetype 1 — Deep-ITM short call …**
#   - [ ] **AC13** — The seed logic …
# Captures the AC number and the trailing description on the same line. The
# description may continue on following lines; we keep only the first line's
# text (a stable, single-line label for the matrix).
_AC_LINE_RE = re.compile(
    r"^\s*-\s*\[[ xX]?\]\s*\*\*AC(?P<num>\d+)\b(?P<rest>.*)$",
)


def _clean_description(raw: str) -> str:
    """Normalise an AC checklist line's trailing text into a one-line label.

    Strips leading separators (``·``, ``—``, ``-``, ``:``), markdown bold
    markers, and collapses whitespace. Returns an empty string if nothing
    meaningful remains.
    """
    text = raw.replace("**", " ")
    text = text.strip()
    text = re.sub(r"^[·—\-:\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_ac_ids(issue_number: int, body: str) -> dict[str, str]:
    """Parse ``#<issue>-AC<n>`` IDs and labels from an issue body.

    Only the first markdown line of each AC contributes the label; multi-line
    AC descriptions keep just their lead line so the registry label stays a
    stable single line. Returns an ordered ``{ac_id: description}`` mapping.
    """
    out: dict[str, str] = {}
    for line in body.splitlines():
        match = _AC_LINE_RE.match(line)
        if not match:
            continue
        ac_id = f"{issue_number}-AC{match.group('num')}"
        out[ac_id] = _clean_description(match.group("rest"))
    return out


def _fetch_issue_body(issue_number: int) -> str:
    """Fetch one issue's markdown body via the ``gh`` CLI (network)."""
    result = subprocess.run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            GH_REPO,
            "--json",
            "body",
            "--jq",
            ".body",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def build_registry(issue_numbers: tuple[int, ...]) -> dict[str, str]:
    """Fetch every adopted issue and merge their ACs into one registry mapping.

    Network step (calls ``gh``). The result is what gets materialized to the
    committed file; the coverage gate never runs this.
    """
    registry: dict[str, str] = {}
    for number in issue_numbers:
        body = _fetch_issue_body(number)
        acs = parse_ac_ids(number, body)
        if not acs:
            logger.warning(
                "sync_ac_registry: issue #%s yielded no AC lines",
                number,
                extra={"event": "sync_ac_registry.no_acs", "outcome": "degraded"},
            )
        registry.update(acs)
    return registry


def _registry_path() -> Path:
    """Committed registry file location (``backend/scripts/ac_registry.json``)."""
    return Path(__file__).resolve().parent / "ac_registry.json"


def render_registry_json(registry: dict[str, str]) -> str:
    """Render the registry as the committed JSON document (stable, diffable)."""
    payload = {
        "_comment": (
            "Generated by backend/scripts/sync_ac_registry.py from adopted issue "
            "bodies. Do not edit by hand — run 'python -m scripts.sync_ac_registry'. "
            "Source of truth: the numbered ACs in each issue body (ADR #356)."
        ),
        "adopted_issues": list(ADOPTED_ISSUES),
        "known_ac_ids": registry,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def load_registry() -> dict[str, str]:
    """Read the committed registry's ``known_ac_ids`` map (offline, no network).

    Used by the coverage gate. Raises ``SystemExit`` if the file is missing so a
    misconfigured checkout fails loudly rather than silently gating on nothing.
    """
    path = _registry_path()
    if not path.is_file():
        raise SystemExit(
            f"sync_ac_registry: registry file not found: {path}. "
            "Run 'python -m scripts.sync_ac_registry' to materialize it."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("known_ac_ids", {}))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Sync (default) or drift-check (--check) the registry."""
    parser = argparse.ArgumentParser(
        prog="sync_ac_registry",
        description=(
            "Materialize the issue-body-derived AC registry into the committed "
            "ac_registry.json (ADR #356). --check fails if the file is stale."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Drift gate: exit 1 if the committed registry differs from the "
        "freshly-synced one. Does not write the file.",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    logger.info(
        "sync_ac_registry starting", extra={"event": "sync_ac_registry.start"}
    )

    try:
        registry = build_registry(ADOPTED_ISSUES)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # Never echo the raw gh stderr (may carry auth/token detail) — log a
        # generic failure and exit non-zero.
        logger.exception(
            "sync_ac_registry: gh issue fetch failed",
            extra={"event": "sync_ac_registry.failed", "outcome": "failed"},
        )
        print("sync_ac_registry: ERROR — failed to fetch issue bodies via gh.")
        return 2

    fresh = render_registry_json(registry)
    path = _registry_path()

    exit_code = 0
    if args.check:
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if existing != fresh:
            print(
                "sync_ac_registry: FAIL — committed ac_registry.json is stale. "
                "Run 'python -m scripts.sync_ac_registry' and commit the result."
            )
            exit_code = 1
        else:
            print(
                f"sync_ac_registry: OK — registry in sync "
                f"({len(registry)} known AC-IDs)."
            )
    else:
        path.write_text(fresh, encoding="utf-8")
        print(f"sync_ac_registry: wrote {path} ({len(registry)} known AC-IDs).")

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "sync_ac_registry complete",
        extra={
            "event": "sync_ac_registry.complete",
            "outcome": "failed" if exit_code else "success",
            "duration_ms": duration_ms,
        },
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
