"""Regenerate backend/openapi/openapi.json from the live FastAPI app.

Run: python -m openapi.regen           (writes the snapshot)
     python -m openapi.regen --check   (exits 1 if stale; no writes)

CWD is backend/ — see CLAUDE.md "API Contract" section once #304 lands.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Important: importing app.main:app does NOT enter the lifespan. The lifespan
# (which does init_db() + Schwab/encryption checks) only runs when the app
# is served (e.g., uvicorn) or wrapped in `with lifespan(app):`. Plain import
# builds the route table only.
from app.main import app

SNAPSHOT_PATH = Path(__file__).parent / "openapi.json"


def generate_spec() -> dict:
    """Return the app's OpenAPI schema dict, with the cache reset.

    Resetting ``app.openapi_schema = None`` guarantees a fresh build each
    call, so ``test_regen_is_idempotent_across_runs`` actually exercises the
    generator rather than reading a cached dict.
    """
    app.openapi_schema = None
    return app.openapi()


def serialize_spec(spec: dict) -> str:
    """Serialize the spec dict to a deterministic JSON string.

    Determinism rules:
      - ``sort_keys=True`` (recursive alphabetical key order)
      - ``indent=2`` (matches ``git diff`` readability conventions)
      - ``ensure_ascii=False`` (don't transform non-ASCII chars in descriptions)
      - trailing newline (POSIX file convention; avoids spurious diffs)
    """
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def cli() -> int:
    """Entry point for ``python -m openapi.regen``.

    Returns the exit code (0 on success, 1 if ``--check`` finds drift). Use
    ``sys.exit(cli())`` from ``__main__``.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the snapshot is stale; do not write.",
    )
    args = parser.parse_args()
    spec = generate_spec()
    desired = serialize_spec(spec)
    if args.check:
        current = SNAPSHOT_PATH.read_text(encoding="utf-8") if SNAPSHOT_PATH.exists() else ""
        if current != desired:
            print("ERROR: backend/openapi/openapi.json is stale.", file=sys.stderr)
            return 1
        print(f"OK: openapi.json matches current code ({len(spec.get('paths', {}))} paths)")
        return 0
    SNAPSHOT_PATH.write_text(desired, encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH} ({len(spec.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
