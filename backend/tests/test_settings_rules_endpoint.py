"""Tests for the Trading Rules config endpoints (issue #158).

``GET``/``PUT /api/settings/rules`` is the typed read/write surface the V1.0
Settings page uses to edit the ``rules_config`` keystone (#156). The generic
``GET /api/settings`` returns a fixed ``SettingsResponse`` and cannot read
``rules_config`` back, so #158 adds this typed pair backed by
:func:`app.services.rules_config.load_rules_config` and the existing
``app_settings`` key/value persistence — no new table, no migration.
"""

import json

from app.models.database import AppSetting, get_db
from app.services.rules_config import (
    DEFAULT_RULES_CONFIG,
    RULES_CONFIG_KEY,
    RULES_CONFIG_SCHEMA_VERSION,
)


def _read_rules_row(client) -> str | None:
    """Read the raw ``rules_config`` value straight from the test DB."""
    from app.main import app

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        entry = db.query(AppSetting).filter(AppSetting.key == RULES_CONFIG_KEY).first()
        return entry.value if entry else None
    finally:
        db.close()


class TestGetRulesConfig:
    """GET /api/settings/rules — read the Trading Rules config."""

    def test_returns_defaults_when_unset(self, client):
        """With no stored row, the endpoint returns the catalog defaults."""
        response = client.get("/api/settings/rules")
        assert response.status_code == 200
        data = response.json()
        assert data == DEFAULT_RULES_CONFIG.model_dump()
        # Spot-check a few catalog defaults and the whole-percent convention.
        assert data["schema_version"] == RULES_CONFIG_SCHEMA_VERSION
        assert data["universe"]["min_open_interest"] == 500
        assert data["entry"]["dte_range"] == {"min": 21, "max": 45}
        assert data["risk"]["loss_review_threshold_pct"] == -15.0
        assert data["management"]["assignment_risk_review"] == "High"

    def test_optional_fields_default_to_null(self, client):
        """The four Optional/unset rules come back as null, not 0."""
        data = client.get("/api/settings/rules").json()
        assert data["universe"]["min_iv_percentile"] is None
        assert data["position"]["max_open_positions"] is None
        assert data["risk"]["hard_max_loss_pct"] is None
        assert data["risk"]["max_consecutive_rolls"] is None

    def test_returns_stored_config(self, client):
        """A stored row is merged over defaults and returned."""
        stored = DEFAULT_RULES_CONFIG.model_dump()
        stored["entry"]["dte_range"] = {"min": 30, "max": 60}
        from app.main import app

        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(AppSetting(key=RULES_CONFIG_KEY, value=json.dumps(stored)))
            db.commit()
        finally:
            db.close()

        data = client.get("/api/settings/rules").json()
        assert data["entry"]["dte_range"] == {"min": 30, "max": 60}


class TestPutRulesConfig:
    """PUT /api/settings/rules — persist the Trading Rules config."""

    def test_persists_and_round_trips(self, client):
        """A valid PUT is stored and the next GET reflects it."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["entry"]["dte_range"] = {"min": 14, "max": 35}
        config["position"]["max_open_positions"] = 8

        put = client.put("/api/settings/rules", json=config)
        assert put.status_code == 200
        assert put.json()["entry"]["dte_range"] == {"min": 14, "max": 35}

        got = client.get("/api/settings/rules").json()
        assert got["entry"]["dte_range"] == {"min": 14, "max": 35}
        assert got["position"]["max_open_positions"] == 8

    def test_optional_field_persists_as_null(self, client):
        """An Optional field sent as null is stored as null — never invented."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["risk"]["hard_max_loss_pct"] = None

        client.put("/api/settings/rules", json=config)
        got = client.get("/api/settings/rules").json()
        assert got["risk"]["hard_max_loss_pct"] is None

        raw = _read_rules_row(client)
        assert raw is not None
        assert json.loads(raw)["risk"]["hard_max_loss_pct"] is None

    def test_schema_version_is_restamped(self, client):
        """A stale schema_version in the body is overwritten on save."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["schema_version"] = 999

        put = client.put("/api/settings/rules", json=config)
        assert put.status_code == 200
        assert put.json()["schema_version"] == RULES_CONFIG_SCHEMA_VERSION

    def test_inverted_range_rejected(self, client):
        """A range with min >= max is rejected with 422 (Pydantic validator)."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["entry"]["dte_range"] = {"min": 45, "max": 21}

        response = client.put("/api/settings/rules", json=config)
        assert response.status_code == 422

    def test_out_of_range_delta_rejected(self, client):
        """A delta bound outside [0, 1] is rejected with 422."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["entry"]["delta_range_csp"] = {"min": 0.2, "max": 1.5}

        response = client.put("/api/settings/rules", json=config)
        assert response.status_code == 422

    def test_positive_loss_threshold_rejected(self, client):
        """A loss threshold must be <= 0 — a positive value is rejected."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["risk"]["loss_review_threshold_pct"] = 15.0

        response = client.put("/api/settings/rules", json=config)
        assert response.status_code == 422

    def test_invalid_save_does_not_persist(self, client):
        """A rejected PUT writes nothing — the next GET is still defaults."""
        config = DEFAULT_RULES_CONFIG.model_dump()
        config["universe"]["min_open_interest"] = -1

        bad = client.put("/api/settings/rules", json=config)
        assert bad.status_code == 422
        assert _read_rules_row(client) is None
        assert client.get("/api/settings/rules").json() == DEFAULT_RULES_CONFIG.model_dump()

    def test_overwrites_existing_row(self, client):
        """A second PUT overwrites the first stored config."""
        first = DEFAULT_RULES_CONFIG.model_dump()
        first["management"]["profit_review_pct"] = 40.0
        client.put("/api/settings/rules", json=first)

        second = DEFAULT_RULES_CONFIG.model_dump()
        second["management"]["profit_review_pct"] = 60.0
        client.put("/api/settings/rules", json=second)

        got = client.get("/api/settings/rules").json()
        assert got["management"]["profit_review_pct"] == 60.0
