"""Integration tests for journal API endpoints (Phase 2)."""


def _create_position(client, **overrides):
    """Helper to POST a position with sensible defaults."""
    payload = {
        "ticker": "AAPL",
        "shares": 100,
        "broker_cost_basis": 5000.0,
        "strategy": "csp",
        "opened_at": "2025-01-15T10:00:00Z",
    }
    payload.update(overrides)
    return client.post("/api/journal/positions", json=payload)


def _create_trade(client, position_id, **overrides):
    """Helper to POST a trade with sensible defaults."""
    payload = {
        "position_id": position_id,
        "trade_type": "sell_put",
        "strike": 48.0,
        "expiration": "2025-02-21",
        "premium": 1.50,
        "fees": 0.65,
        "quantity": 1,
        "opened_at": "2025-01-15T10:00:00Z",
    }
    payload.update(overrides)
    return client.post("/api/journal/trades", json=payload)


# --- GET /api/journal/positions ---


def test_list_positions_empty(client):
    resp = client.get("/api/journal/positions")
    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_list_positions_returns_created(client):
    _create_position(client)
    resp = client.get("/api/journal/positions")
    assert resp.status_code == 200
    positions = resp.json()["positions"]
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"


def test_list_positions_filter_by_status(client):
    _create_position(client, ticker="AAPL")
    r2 = _create_position(client, ticker="MSFT")
    pos_id = r2.json()["id"]
    client.put(f"/api/journal/positions/{pos_id}", json={"status": "closed"})

    open_resp = client.get("/api/journal/positions?status=open")
    assert len(open_resp.json()["positions"]) == 1
    assert open_resp.json()["positions"][0]["ticker"] == "AAPL"

    closed_resp = client.get("/api/journal/positions?status=closed")
    assert len(closed_resp.json()["positions"]) == 1
    assert closed_resp.json()["positions"][0]["ticker"] == "MSFT"


# --- GET /api/journal/positions/{id} ---


def test_get_position_by_id(client):
    r = _create_position(client)
    pos_id = r.json()["id"]
    resp = client.get(f"/api/journal/positions/{pos_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == pos_id
    assert data["ticker"] == "AAPL"
    assert "total_premiums" in data
    assert "adjusted_cost_basis" in data
    assert "min_compliant_cc_strike" in data
    assert "trades" in data


def test_get_position_not_found(client):
    resp = client.get("/api/journal/positions/nonexistent")
    assert resp.status_code == 404


# --- POST /api/journal/positions ---


def test_create_position(client):
    resp = _create_position(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["shares"] == 100
    assert data["broker_cost_basis"] == 5000.0
    assert data["strategy"] == "csp"
    assert data["status"] == "open"
    assert len(data["id"]) == 36


def test_create_position_invalid_strategy(client):
    resp = _create_position(client, strategy="invalid")
    assert resp.status_code == 422


def test_create_position_zero_shares(client):
    resp = _create_position(client, shares=0)
    assert resp.status_code == 422


# --- PUT /api/journal/positions/{id} ---


def test_update_position(client):
    r = _create_position(client)
    pos_id = r.json()["id"]
    resp = client.put(
        f"/api/journal/positions/{pos_id}",
        json={"notes": "Updated", "broker_cost_basis": 4800.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["notes"] == "Updated"
    assert data["broker_cost_basis"] == 4800.0
    assert data["ticker"] == "AAPL"


def test_update_position_not_found(client):
    resp = client.put(
        "/api/journal/positions/nonexistent", json={"notes": "test"}
    )
    assert resp.status_code == 404


# --- POST /api/journal/trades ---


def test_create_trade(client):
    pos = _create_position(client).json()
    resp = _create_trade(client, pos["id"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["position_id"] == pos["id"]
    assert data["trade_type"] == "sell_put"
    assert data["strike"] == 48.0
    assert data["premium"] == 1.50


def test_create_trade_invalid_position(client):
    resp = _create_trade(client, "nonexistent-id")
    assert resp.status_code == 404


def test_create_trade_invalid_trade_type(client):
    pos = _create_position(client).json()
    resp = _create_trade(client, pos["id"], trade_type="invalid")
    assert resp.status_code == 422


# --- PUT /api/journal/trades/{id} ---


def test_update_trade(client):
    pos = _create_position(client).json()
    trade = _create_trade(client, pos["id"]).json()
    resp = client.put(
        f"/api/journal/trades/{trade['id']}",
        json={"premium": 2.00, "close_reason": "fifty_pct_target"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["premium"] == 2.00
    assert data["close_reason"] == "fifty_pct_target"
    assert data["strike"] == 48.0


def test_update_trade_not_found(client):
    resp = client.put(
        "/api/journal/trades/nonexistent", json={"premium": 2.00}
    )
    assert resp.status_code == 404


# --- DELETE /api/journal/trades/{id} ---


def test_delete_trade(client):
    pos = _create_position(client).json()
    trade = _create_trade(client, pos["id"]).json()
    resp = client.delete(f"/api/journal/trades/{trade['id']}")
    assert resp.status_code == 204

    # Verify trade is gone from position
    pos_resp = client.get(f"/api/journal/positions/{pos['id']}")
    assert len(pos_resp.json()["trades"]) == 0


def test_delete_trade_not_found(client):
    resp = client.delete("/api/journal/trades/nonexistent")
    assert resp.status_code == 404


# --- Computed fields via API ---


def test_adjusted_basis_via_api(client):
    pos = _create_position(client, broker_cost_basis=5000.0).json()
    _create_trade(client, pos["id"], premium=1.50, quantity=1)  # 150
    _create_trade(client, pos["id"], premium=2.00, quantity=1)  # 200

    resp = client.get(f"/api/journal/positions/{pos['id']}")
    data = resp.json()
    assert data["total_premiums"] == 350.0
    assert data["adjusted_cost_basis"] == 4650.0
    # (4650 / 100) * 1.10 = 51.15
    assert data["min_compliant_cc_strike"] == 51.15


def test_adjusted_basis_mixed_trades_via_api(client):
    pos = _create_position(client, broker_cost_basis=5000.0).json()
    _create_trade(client, pos["id"], premium=2.00, quantity=1)  # +200
    _create_trade(
        client, pos["id"], trade_type="buy_put_close", premium=-0.50, quantity=1
    )  # -50

    resp = client.get(f"/api/journal/positions/{pos['id']}")
    data = resp.json()
    assert data["total_premiums"] == 150.0
    assert data["adjusted_cost_basis"] == 4850.0


def test_position_with_trades_in_list(client):
    """Verify list endpoint includes computed fields."""
    pos = _create_position(client, broker_cost_basis=5000.0).json()
    _create_trade(client, pos["id"], premium=1.50, quantity=1)

    resp = client.get("/api/journal/positions")
    positions = resp.json()["positions"]
    assert len(positions) == 1
    assert positions[0]["total_premiums"] == 150.0
    assert positions[0]["adjusted_cost_basis"] == 4850.0


# --- Input validation via API ---


def test_invalid_status_query_param(client):
    """Invalid status query param should return 422."""
    resp = client.get("/api/journal/positions?status=bogus")
    assert resp.status_code == 422


def test_update_position_negative_shares(client):
    """shares=-1 in update should return 422."""
    pos = _create_position(client).json()
    resp = client.put(
        f"/api/journal/positions/{pos['id']}", json={"shares": -1}
    )
    assert resp.status_code == 422


def test_create_trade_zero_quantity(client):
    """quantity=0 should return 422."""
    pos = _create_position(client).json()
    resp = _create_trade(client, pos["id"], quantity=0)
    assert resp.status_code == 422


def test_update_trade_zero_quantity(client):
    """quantity=0 in trade update should return 422."""
    pos = _create_position(client).json()
    trade = _create_trade(client, pos["id"]).json()
    resp = client.put(
        f"/api/journal/trades/{trade['id']}", json={"quantity": 0}
    )
    assert resp.status_code == 422


def test_update_position_strategy(client):
    """Strategy can be corrected via update."""
    pos = _create_position(client, strategy="csp").json()
    resp = client.put(
        f"/api/journal/positions/{pos['id']}", json={"strategy": "wheel"}
    )
    assert resp.status_code == 200
    assert resp.json()["strategy"] == "wheel"


def test_update_position_invalid_strategy(client):
    """Invalid strategy in update should return 422."""
    pos = _create_position(client).json()
    resp = client.put(
        f"/api/journal/positions/{pos['id']}", json={"strategy": "invalid"}
    )
    assert resp.status_code == 422
