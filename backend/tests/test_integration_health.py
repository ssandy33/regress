from unittest.mock import patch


class TestHealthEndpoints:
    def test_health_check(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_sources(self, client):
        with (
            patch("app.routers.health._check_alpha_vantage", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": False, "error": "No key"}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
        ):
            response = client.get("/api/health/sources")
            assert response.status_code == 200
            data = response.json()
            assert data["alpha_vantage"]["available"] is True
            assert data["fred"]["available"] is False
            assert data["zillow"]["available"] is True
            assert data["all_down"] is False
