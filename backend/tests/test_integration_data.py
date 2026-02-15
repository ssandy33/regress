from unittest.mock import patch

from app.services.data_fetcher import DataFetcher, InvalidTickerError


class TestDataEndpoints:
    def test_get_historical_data(self, client, mock_fetcher):
        response = client.get("/api/data/AAPL?start=2023-01-01&end=2023-03-01")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "data_meta" in data
        assert len(data["data"]) == 60
        assert all("date" in pt and "value" in pt for pt in data["data"])

    def test_get_data_invalid_ticker(self, client):
        with patch.object(DataFetcher, "fetch", side_effect=InvalidTickerError("Unknown ticker 'XXXX'")):
            response = client.get("/api/data/XXXX?start=2023-01-01&end=2023-03-01")
            assert response.status_code == 404
