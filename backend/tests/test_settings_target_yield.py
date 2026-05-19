"""Tests for the okr_target_yield read/write plumbing (issue #207).

The V1.0.3 stopgap that gives the Recovery Plan "Set target yield →" CTA a
real destination. Covers AC1 — the value round-trips through the generic
settings endpoints — and the CLAUDE.md boundary-validation discipline.

Uses the in-memory SQLite ``client`` fixture from ``conftest.py``.
"""

from app.models.database import AppSetting, get_db


def _stored_target_yield(client) -> object:
    """Return the raw okr_target_yield app_settings value, or None if absent."""
    from app.main import app

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        entry = (
            db.query(AppSetting)
            .filter(AppSetting.key == "okr_target_yield")
            .first()
        )
        return entry.value if entry else None
    finally:
        db.close()


class TestTargetYieldRead:
    """GET /api/settings carries okr_target_yield (AC1)."""

    def test_get_settings_target_yield_none_when_unseeded(self, client):
        """No stored row → okr_target_yield is null."""
        response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["okr_target_yield"] is None

    def test_put_then_get_round_trips_fraction(self, client):
        """PUT a fraction, then GET returns the same fraction (AC1)."""
        put_resp = client.put(
            "/api/settings",
            json={"key": "okr_target_yield", "value": "0.12"},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["key"] == "okr_target_yield"

        get_resp = client.get("/api/settings")
        assert get_resp.status_code == 200
        assert get_resp.json()["okr_target_yield"] == 0.12

    def test_get_settings_target_yield_none_when_row_malformed(self, client):
        """A non-numeric stored row degrades to None — never breaks the read."""
        client.put(
            "/api/settings",
            json={"key": "okr_target_yield", "value": "not-a-number"},
        )
        # The PUT itself is rejected (see TestTargetYieldValidation), so seed
        # the malformed row directly to exercise the defensive GET parse.
        from app.main import app

        override = app.dependency_overrides[get_db]
        db = next(override())
        try:
            db.add(AppSetting(key="okr_target_yield", value="garbage"))
            db.commit()
        finally:
            db.close()

        response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["okr_target_yield"] is None


class TestTargetYieldValidation:
    """PUT /api/settings boundary validation for okr_target_yield (AC1)."""

    def test_put_above_upper_bound_rejected(self, client):
        """A fraction > 1.0 is rejected with a generic 422."""
        response = client.put(
            "/api/settings",
            json={"key": "okr_target_yield", "value": "1.5"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail == "Target yield must be between 0% and 100%."
        # No row written on a rejected value.
        assert _stored_target_yield(client) is None

    def test_put_at_or_below_zero_rejected(self, client):
        """A non-positive fraction is rejected (0% is meaningless / out of bounds)."""
        for bad in ("-0.1", "0", "0.0"):
            response = client.put(
                "/api/settings",
                json={"key": "okr_target_yield", "value": bad},
            )
            assert response.status_code == 422, bad
            assert (
                response.json()["detail"]
                == "Target yield must be between 0% and 100%."
            )
        assert _stored_target_yield(client) is None

    def test_put_non_numeric_rejected_without_leaking_exception(self, client):
        """A non-numeric value is rejected; the raw parse exception never leaks."""
        response = client.put(
            "/api/settings",
            json={"key": "okr_target_yield", "value": "abc"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail == "Target yield must be between 0% and 100%."
        # CLAUDE.md — generic copy only, no raw ValueError text.
        assert "could not convert" not in detail
        assert "float" not in detail
        assert _stored_target_yield(client) is None

    def test_put_nan_and_inf_rejected(self, client):
        """NaN / inf parse as floats but are out of bounds — rejected."""
        for bad in ("nan", "inf", "-inf"):
            response = client.put(
                "/api/settings",
                json={"key": "okr_target_yield", "value": bad},
            )
            assert response.status_code == 422, bad
        assert _stored_target_yield(client) is None

    def test_put_at_bounds_accepted(self, client):
        """The inclusive upper bound (1.0) and small positive values are accepted."""
        for good in ("1.0", "0.0001"):
            response = client.put(
                "/api/settings",
                json={"key": "okr_target_yield", "value": good},
            )
            assert response.status_code == 200, good

    def test_other_keys_pass_through_unchanged(self, client):
        """The boundary check only gates okr_target_yield — other keys are blind upserts."""
        response = client.put(
            "/api/settings",
            json={"key": "theme", "value": "dark"},
        )
        assert response.status_code == 200
        assert client.get("/api/settings").json()["theme"] == "dark"
