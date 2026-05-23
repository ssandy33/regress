"""API tests for the thesis endpoints (issue #280, Worker F).

Covers the eight required scenarios from the worker brief:

1. GET with no note → empty-state shape (``thesis=null``, ``version=0``).
2. PUT creates a row, GET returns it with ``version=1``.
3. PUT updates an existing note — ``version`` increments,
   ``updated_at`` refreshes, body changes.
4. PUT with > 4000 chars → 422 with sanitized detail.
5. PUT with empty string → allowed, version increments.
6. GET on a non-existent position → 404 with sanitized detail.
7. PUT on a non-existent position → 404 with sanitized detail.
8. ``body`` is the column name and the text round-trips cleanly.
"""

from __future__ import annotations
import pytest


def _create_position(client, ticker: str = "AAPL") -> str:
    """POST a minimal position and return its id."""
    resp = client.post(
        "/api/journal/positions",
        json={
            "ticker": ticker,
            "shares": 100,
            "broker_cost_basis": 15000.0,
            "opened_at": "2026-01-15T10:00:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- GET ---


@pytest.mark.integration
def test_get_thesis_empty_state_when_no_row(client):
    """Position exists but no thesis row → empty-state shape (NOT 404)."""
    pid = _create_position(client)
    resp = client.get(f"/api/positions/{pid}/research/thesis")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"thesis": None, "updated_at": None, "version": 0}


@pytest.mark.integration
def test_get_thesis_404_for_missing_position(client):
    """A missing position id returns sanitized 404."""
    resp = client.get("/api/positions/does-not-exist/research/thesis")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Position not found"}


# --- PUT create ---


@pytest.mark.integration
def test_put_creates_row_version_one(client):
    """First PUT creates the row at version 1; GET returns it."""
    pid = _create_position(client)
    put_resp = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": "Initial thesis on the company"},
    )
    assert put_resp.status_code == 200
    payload = put_resp.json()
    assert payload["thesis"] == "Initial thesis on the company"
    assert payload["version"] == 1
    assert payload["updated_at"] is not None

    # GET reflects the same row.
    get_resp = client.get(f"/api/positions/{pid}/research/thesis")
    assert get_resp.status_code == 200
    assert get_resp.json() == payload


@pytest.mark.integration
def test_put_404_for_missing_position(client):
    """PUT on a missing position id returns sanitized 404."""
    resp = client.put(
        "/api/positions/does-not-exist/research/thesis",
        json={"thesis": "anything"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Position not found"}


# --- PUT update / versioning ---


@pytest.mark.integration
def test_put_update_increments_version_and_refreshes_updated_at(client):
    """Second PUT bumps version, refreshes updated_at, replaces body."""
    pid = _create_position(client)
    first = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": "v1 body"},
    ).json()
    assert first["version"] == 1

    second = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": "v2 body, revised after earnings"},
    ).json()
    assert second["version"] == 2
    assert second["thesis"] == "v2 body, revised after earnings"
    # updated_at advances monotonically (or stays equal at the ISO
    # millisecond floor — accept >= to keep the test robust on fast
    # in-memory DBs).
    assert second["updated_at"] >= first["updated_at"]


@pytest.mark.integration
def test_put_three_times_increments_version_each_call(client):
    """Three sequential PUTs land at versions 1, 2, 3 in order."""
    pid = _create_position(client)
    versions = []
    for n in range(1, 4):
        resp = client.put(
            f"/api/positions/{pid}/research/thesis",
            json={"thesis": f"v{n}"},
        )
        assert resp.status_code == 200
        versions.append(resp.json()["version"])
    assert versions == [1, 2, 3]


# --- PUT validation ---


@pytest.mark.integration
def test_put_rejects_over_4000_chars(client):
    """Bodies longer than the cap return 422 with a sanitized message."""
    pid = _create_position(client)
    too_long = "x" * 4001
    resp = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": too_long},
    )
    assert resp.status_code == 422
    # Pydantic surfaces its own detail on validation; we only assert the
    # response is sanitized (no ``str(e)`` traceback leaks). The body
    # text MUST NOT contain "Traceback" or sensitive markers.
    text = resp.text
    assert "Traceback" not in text
    # The router fallback message and the Pydantic message both mention
    # the cap in human-readable form; either is acceptable.
    assert "4000" in text or "limit" in text.lower() or "length" in text.lower()


@pytest.mark.integration
def test_put_accepts_exactly_4000_chars(client):
    """Exactly 4000 characters is within the cap (boundary)."""
    pid = _create_position(client)
    boundary = "y" * 4000
    resp = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": boundary},
    )
    assert resp.status_code == 200
    assert resp.json()["thesis"] == boundary


@pytest.mark.integration
def test_put_empty_string_is_allowed_and_bumps_version(client):
    """Empty body clears the note but still increments the version."""
    pid = _create_position(client)
    first = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": "something to clear"},
    ).json()
    cleared = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": ""},
    )
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["thesis"] == ""
    assert body["version"] == first["version"] + 1


# --- Round-trip / sanity ---


@pytest.mark.integration
def test_body_column_round_trips_complex_text(client):
    """``body`` round-trips newlines, unicode, and punctuation losslessly."""
    pid = _create_position(client)
    original = "Line 1\n\nLine 2 — café — and a 中文 character."
    put_resp = client.put(
        f"/api/positions/{pid}/research/thesis",
        json={"thesis": original},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["thesis"] == original

    get_resp = client.get(f"/api/positions/{pid}/research/thesis")
    assert get_resp.json()["thesis"] == original


@pytest.mark.integration
def test_two_positions_have_independent_notes(client):
    """Each position has its own thesis — no cross-pollination."""
    pid_a = _create_position(client, ticker="AAPL")
    pid_b = _create_position(client, ticker="MSFT")

    client.put(
        f"/api/positions/{pid_a}/research/thesis",
        json={"thesis": "thesis A"},
    )
    client.put(
        f"/api/positions/{pid_b}/research/thesis",
        json={"thesis": "thesis B"},
    )

    a = client.get(f"/api/positions/{pid_a}/research/thesis").json()
    b = client.get(f"/api/positions/{pid_b}/research/thesis").json()
    assert a["thesis"] == "thesis A"
    assert b["thesis"] == "thesis B"
