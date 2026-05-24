"""Unit tests for the deterministic OpenAPI snapshot regen script.

Contract v1 — Wave 1, Issue #302. These tests pin the behavior of
``backend/openapi/regen.py`` so the committed ``backend/openapi/openapi.json``
remains a faithful, byte-stable snapshot of the live FastAPI app.

All tests are pure-Python unit tests (PRD #261 / R3):
``generate_spec()`` walks the in-memory route table — no FastAPI TestClient,
no DB session, no network. Safe to tag ``@pytest.mark.unit``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openapi import regen


@pytest.mark.unit
def test_regen_produces_non_empty_snapshot():
    """T-302.1 (AC-2.3): generate_spec() returns a non-empty OpenAPI dict.

    Asserts the spec contains the four canonical top-level keys
    (``openapi``, ``info``, ``paths``, ``components``) and a substantive
    path count. Bound is intentionally conservative — the snapshot has 53
    paths today; 40 leaves headroom for de-listings without becoming
    a meaningless smoke check.
    """
    spec = regen.generate_spec()
    assert isinstance(spec, dict)
    for key in ("openapi", "info", "paths", "components"):
        assert key in spec, f"missing top-level key: {key!r}"
    assert len(spec["paths"]) >= 40, (
        f"expected at least 40 routes in the snapshot, got {len(spec['paths'])}"
    )


@pytest.mark.unit
def test_serialize_is_deterministic():
    """T-302.2 (AC-2.1, AC-2.2): serializing the same dict twice is byte-equal.

    The determinism contract (sort_keys + indent=2 + ensure_ascii=False +
    trailing newline) is what makes the snapshot a reliable git-diff target.
    """
    spec = regen.generate_spec()
    assert regen.serialize_spec(spec) == regen.serialize_spec(spec)


@pytest.mark.unit
def test_regen_is_idempotent_across_runs():
    """T-302.3 (AC-2.1, AC-2.2): two regen passes produce byte-equal strings.

    Catches non-determinism that ``test_serialize_is_deterministic`` cannot —
    e.g., a future ``@router.api_route(["GET", "POST"], ...)`` would yield
    a ``set``-derived ``operationId`` ordering that flips between runs.
    Resetting ``app.openapi_schema = None`` inside ``generate_spec()`` forces
    a fresh build each call rather than returning FastAPI's cached dict.
    """
    first = regen.serialize_spec(regen.generate_spec())
    second = regen.serialize_spec(regen.generate_spec())
    assert first == second


@pytest.mark.unit
def test_snapshot_file_matches_regen():
    """T-302.4 (AC-1.1): the committed snapshot matches what regen produces.

    This is the same check CI's drift step (#303) will re-run via
    ``python -m openapi.regen --check``. If this test fails locally, the
    snapshot is stale — regen it with ``python -m openapi.regen``.
    """
    on_disk = regen.SNAPSHOT_PATH.read_text(encoding="utf-8")
    fresh = regen.serialize_spec(regen.generate_spec())
    assert on_disk == fresh, (
        "Committed backend/openapi/openapi.json is stale. "
        "Run `python -m openapi.regen` from CWD=backend/ to refresh it."
    )


@pytest.mark.unit
def test_regen_check_passes_when_snapshot_fresh(monkeypatch, capsys):
    """T-302.5 (AC-3.2, cross-issue with #303): --check exits 0 on fresh snapshot.

    The on-disk snapshot is committed and matches the live code (enforced by
    T-302.4 above), so ``cli()`` with ``--check`` must return 0 without
    writing anything.
    """
    monkeypatch.setattr(sys, "argv", ["regen.py", "--check"])
    rc = regen.cli()
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out


@pytest.mark.unit
def test_regen_check_fails_when_snapshot_stale(monkeypatch, capsys, tmp_path):
    """T-302.6 (AC-3.3, cross-issue with #303): --check exits 1 on stale snapshot.

    Redirect ``SNAPSHOT_PATH`` at a tmp file containing deliberately stale
    content; ``cli(--check)`` must exit 1 with the exact stderr message
    that #303's CI step will key on.
    """
    stale_path = tmp_path / "openapi.json"
    stale_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(regen, "SNAPSHOT_PATH", stale_path)
    monkeypatch.setattr(sys, "argv", ["regen.py", "--check"])

    rc = regen.cli()
    assert rc == 1
    captured = capsys.readouterr()
    assert "stale" in captured.err
    assert "ERROR: backend/openapi/openapi.json is stale." in captured.err
