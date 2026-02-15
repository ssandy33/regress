from unittest.mock import patch


class TestAssetSearchEndpoints:
    def test_search_assets_offline(self, client):
        response = client.get("/api/assets/search?q=SP&offline=true")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) > 0
        identifiers = [r["identifier"] for r in results]
        assert "^GSPC" in identifiers

    def test_search_assets_with_yahoo_mocked(self, client):
        with (
            patch("app.routers.assets._validate_ticker_yahoo", return_value=None),
            patch("app.routers.assets._search_yahoo", return_value=[]),
        ):
            response = client.get("/api/assets/search?q=SP")
            assert response.status_code == 200
            assert len(response.json()["results"]) > 0

    def test_case_shiller_list(self, client):
        response = client.get("/api/assets/case-shiller")
        assert response.status_code == 200
        metros = response.json()["metros"]
        assert len(metros) > 0
        assert any("Case-Shiller" in m["name"] for m in metros)

    def test_suggest_tickers(self, client):
        response = client.get("/api/assets/suggest?q=GC")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "GC"
        assert "suggestions" in data
