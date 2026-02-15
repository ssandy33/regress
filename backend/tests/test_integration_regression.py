from unittest.mock import patch


class TestLinearRegression:
    def test_linear_success(self, client, mock_fetcher):
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.get_earnings_dates.return_value = None
            response = client.post("/api/regression/linear", json={
                "asset": "AAPL",
                "start_date": "2023-01-01",
                "end_date": "2023-03-01",
            })
        assert response.status_code == 200
        data = response.json()
        assert "slope" in data
        assert "r_squared" in data
        assert "predicted_values" in data
        assert len(data["dates"]) == 60


class TestMultiFactorRegression:
    def test_multi_factor_success(self, client, multi_asset_fetcher):
        response = client.post("/api/regression/multi-factor", json={
            "dependent": "CSUSHPINSA",
            "independents": ["DGS10", "^GSPC"],
            "start_date": "2023-01-01",
            "end_date": "2023-03-01",
        })
        assert response.status_code == 200
        data = response.json()
        assert "coefficients" in data
        assert "r_squared" in data
        assert "alignment_notes" in data


class TestRollingRegression:
    def test_rolling_success(self, client, mock_fetcher):
        response = client.post("/api/regression/rolling", json={
            "asset": "AAPL",
            "start_date": "2023-01-01",
            "end_date": "2023-03-01",
            "window_size": 10,
        })
        assert response.status_code == 200
        data = response.json()
        assert "slope_over_time" in data
        assert "r_squared_over_time" in data
        assert len(data["slope_over_time"]) == 51  # 60 - 10 + 1


class TestCompareRegression:
    def test_compare_success(self, client, multi_asset_fetcher):
        response = client.post("/api/regression/compare", json={
            "assets": ["AAPL", "^GSPC"],
            "start_date": "2023-01-01",
            "end_date": "2023-03-01",
        })
        assert response.status_code == 200
        data = response.json()
        assert "series" in data
        assert "AAPL" in data["series"]
        assert "^GSPC" in data["series"]
        assert "stats" in data

    def test_compare_too_few_assets(self, client):
        response = client.post("/api/regression/compare", json={
            "assets": ["AAPL"],
            "start_date": "2023-01-01",
            "end_date": "2023-03-01",
        })
        assert response.status_code == 400
