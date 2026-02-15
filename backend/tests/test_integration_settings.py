class TestSettingsEndpoints:
    def test_get_settings(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "fred_api_key_set" in data
        assert "cache_ttl_daily_hours" in data
        assert "theme" in data

    def test_update_setting(self, client):
        response = client.put("/api/settings", json={"key": "theme", "value": "dark"})
        assert response.status_code == 200
        assert response.json()["key"] == "theme"
        get_resp = client.get("/api/settings")
        assert get_resp.json()["theme"] == "dark"

    def test_get_cache_stats_empty(self, client):
        response = client.get("/api/settings/cache")
        assert response.status_code == 200
        data = response.json()
        assert data["entry_count"] == 0
        assert data["total_size_bytes"] == 0
