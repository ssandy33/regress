"""Unit tests for ``backend/scripts/sync_ac_registry.py`` (ADR #356, Decision 4).

Pure-Python: no FastAPI app, no DB, NO network. The ``gh``-calling paths
(``build_registry`` / ``main``) are deliberately NOT exercised here — these tests
cover the offline halves: parsing AC checklist lines out of an issue body,
normalising the labels, rendering the committed JSON, and the offline
``load_registry()`` read the coverage gate depends on.
"""

from __future__ import annotations

import json

import pytest

from scripts import sync_ac_registry as sync


# A representative slice of an issue body in the feature-writer's AC format.
_ISSUE_BODY = """\
## Acceptance criteria

Some preamble prose that is not an AC.

- [ ] **AC1 · Archetype 1 — Deep-ITM short call, >14 DTE, delta ~0.9**
  Validates: #318 → assignment risk renders as "High"
- [ ] **AC2** — Near-the-money short call, ≤14 DTE
- [x] **AC3:** OTM short call, long DTE
- A bullet that is not an AC checklist line.
"""


@pytest.mark.unit
def test_parse_ac_ids_namespaces_with_issue_number():
    """Each ``AC<n>`` becomes ``<issue>-AC<n>`` with a single-line label."""
    acs = sync.parse_ac_ids(349, _ISSUE_BODY)
    assert set(acs) == {"349-AC1", "349-AC2", "349-AC3"}


@pytest.mark.unit
def test_parse_ac_ids_keeps_only_first_line_label():
    """A multi-line AC keeps just its lead line as the label (stable, single line)."""
    acs = sync.parse_ac_ids(349, _ISSUE_BODY)
    assert acs["349-AC1"].startswith("Archetype 1 — Deep-ITM short call")
    # The "Validates:" continuation line is NOT folded into the label.
    assert "Validates" not in acs["349-AC1"]


@pytest.mark.unit
def test_parse_ac_ids_handles_checked_and_unchecked_boxes():
    """Both ``[ ]`` and ``[x]`` checklist states are parsed."""
    acs = sync.parse_ac_ids(349, _ISSUE_BODY)
    assert acs["349-AC3"] == "OTM short call, long DTE"


@pytest.mark.unit
def test_parse_ac_ids_ignores_non_ac_bullets():
    """Plain bullets and prose are not mistaken for ACs."""
    acs = sync.parse_ac_ids(349, _ISSUE_BODY)
    assert len(acs) == 3


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" · Deep-ITM call**", "Deep-ITM call"),
        ("** — Near the money", "Near the money"),
        (":  OTM call", "OTM call"),
        ("   ", ""),
    ],
)
def test_clean_description_strips_separators_and_bold(raw, expected):
    """Leading separators / bold markers are stripped; whitespace collapsed."""
    assert sync._clean_description(raw) == expected


@pytest.mark.unit
def test_render_registry_json_is_stable_and_parseable():
    """The rendered JSON carries the registry payload and round-trips."""
    rendered = sync.render_registry_json({"349-AC1": "first", "349-AC2": "second"})
    data = json.loads(rendered)
    assert data["adopted_issues"] == list(sync.ADOPTED_ISSUES)
    assert data["known_ac_ids"] == {"349-AC1": "first", "349-AC2": "second"}
    assert "_comment" in data
    # Trailing newline keeps the committed file POSIX-clean / diff-stable.
    assert rendered.endswith("\n")


@pytest.mark.unit
def test_load_registry_reads_known_ac_ids(tmp_path, monkeypatch):
    """load_registry() returns the committed file's ``known_ac_ids`` map (offline)."""
    reg = tmp_path / "ac_registry.json"
    reg.write_text(
        json.dumps({"known_ac_ids": {"349-AC1": "x", "349-AC2": "y"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "_registry_path", lambda: reg)
    assert sync.load_registry() == {"349-AC1": "x", "349-AC2": "y"}


@pytest.mark.unit
def test_load_registry_raises_when_file_missing(tmp_path, monkeypatch):
    """A missing registry file fails loudly (SystemExit), not silently empty."""
    monkeypatch.setattr(sync, "_registry_path", lambda: tmp_path / "absent.json")
    with pytest.raises(SystemExit):
        sync.load_registry()


@pytest.mark.unit
def test_committed_registry_matches_issue_349_acs():
    """The committed ac_registry.json holds all 13 #349 AC-IDs (smoke of the seed).

    Reads the real committed file via the module's own ``load_registry`` — this
    is the offline read the coverage gate performs, so it must stay green.
    """
    known = sync.load_registry()
    expected = {f"349-AC{n}" for n in range(1, 14)}
    assert expected <= set(known)
