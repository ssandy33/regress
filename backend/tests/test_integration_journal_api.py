"""Integration tests for journal API endpoints (Phase 2)."""


def _create_position(client, **overrides):
    """Helper to POST a position with sensible defaults.

    Per issue #131 the ``strategy`` field is no longer accepted on
    PositionCreate; the server seeds it with "csp" and the recomputer
    overwrites it on the first import. Tests that still want to override
    the seeded strategy can do so via direct ORM manipulation.
    """
    payload = {
        "ticker": "AAPL",
        "shares": 100,
        "broker_cost_basis": 5000.0,
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
    # Per #131, manually-created positions seed with "csp" until a trade
    # is logged and the recomputer derives the real label.
    assert data["strategy"] == "csp"
    assert data["status"] == "open"
    assert len(data["id"]) == 36


def test_create_position_ignores_strategy_field(client):
    """Issue #131: ``strategy`` is no longer accepted on PositionCreate.

    Pydantic ignores unknown fields by default, so a payload that still
    sends ``strategy`` must succeed and the seeded "csp" label must win.
    """
    resp = _create_position(client, strategy="wheel")
    assert resp.status_code == 201
    assert resp.json()["strategy"] == "csp"


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


# --- DELETE /api/journal/positions/{id} ---


def test_delete_position_success_cascades_trades(client):
    """Deleting a position removes the row and every child trade in one shot."""
    pos = _create_position(client).json()
    _create_trade(client, pos["id"], premium=1.5, quantity=1)
    _create_trade(client, pos["id"], premium=2.0, quantity=2)

    # Sanity check: trades exist before delete
    pre = client.get(f"/api/journal/positions/{pos['id']}")
    assert pre.status_code == 200
    assert len(pre.json()["trades"]) == 2

    resp = client.delete(f"/api/journal/positions/{pos['id']}")
    assert resp.status_code == 204

    # Position is gone
    after = client.get(f"/api/journal/positions/{pos['id']}")
    assert after.status_code == 404

    # And it doesn't reappear in the list
    listing = client.get("/api/journal/positions").json()
    assert listing["positions"] == []


def test_delete_position_not_found(client):
    resp = client.delete("/api/journal/positions/does-not-exist")
    assert resp.status_code == 404


def test_delete_position_does_not_touch_other_positions(client):
    """Deleting one position leaves siblings intact."""
    keep = _create_position(client, ticker="AAPL").json()
    drop = _create_position(client, ticker="MSFT").json()
    _create_trade(client, keep["id"], premium=1.0)
    _create_trade(client, drop["id"], premium=2.0)

    resp = client.delete(f"/api/journal/positions/{drop['id']}")
    assert resp.status_code == 204

    surviving = client.get("/api/journal/positions").json()["positions"]
    assert len(surviving) == 1
    assert surviving[0]["id"] == keep["id"]
    assert len(surviving[0]["trades"]) == 1


def test_delete_position_500_does_not_leak_exception_text(client, monkeypatch):
    """If the service raises, the response stays generic — no ``str(e)`` leak."""
    from app.routers import journal as journal_router

    secret = "boom-secret-leak-message"

    def _raise(_db, _pid):
        raise RuntimeError(secret)

    monkeypatch.setattr(journal_router, "delete_position", _raise)

    pos = _create_position(client).json()
    resp = client.delete(f"/api/journal/positions/{pos['id']}")
    assert resp.status_code == 500
    assert secret not in resp.text
    assert resp.json()["detail"] == "An unexpected error occurred"


# --- DELETE /api/journal/all ---


def test_clear_all_journal_wipes_everything(client):
    """Clear-all removes every position and trade and returns pre-delete counts."""
    p1 = _create_position(client, ticker="AAPL").json()
    p2 = _create_position(client, ticker="MSFT").json()
    _create_trade(client, p1["id"], premium=1.0)
    _create_trade(client, p1["id"], premium=2.0)
    _create_trade(client, p2["id"], premium=3.0)

    resp = client.delete("/api/journal/all")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"deleted_positions": 2, "deleted_trades": 3}

    after = client.get("/api/journal/positions").json()
    assert after["positions"] == []


def test_clear_all_journal_when_already_empty(client):
    """Empty journal still returns a well-formed zero-count payload."""
    resp = client.delete("/api/journal/all")
    assert resp.status_code == 200
    assert resp.json() == {"deleted_positions": 0, "deleted_trades": 0}


def test_clear_all_journal_500_does_not_leak_exception_text(client, monkeypatch):
    """Clear-all 500 errors are generic."""
    from app.routers import journal as journal_router

    secret = "another-boom-secret"

    def _raise(_db):
        raise RuntimeError(secret)

    monkeypatch.setattr(journal_router, "clear_all_journal_data", _raise)

    resp = client.delete("/api/journal/all")
    assert resp.status_code == 500
    assert secret not in resp.text
    assert resp.json()["detail"] == "An unexpected error occurred"


# --- POST /api/journal/reconcile (issue #139) ---


def _seed_full_cycle(client):
    """Seed a position whose stored state is stale relative to its ledger.

    Pre-fix imports (issue #127) left ``shares=100`` even after assignment
    plus called_away should have driven the position to closed/0 shares.
    Returns the created position dict.
    """
    pos = _create_position(client, ticker="MARA", broker_cost_basis=0.0).json()
    pid = pos["id"]
    _create_trade(
        client,
        pid,
        trade_type="sell_put",
        strike=20.0,
        expiration="2026-02-20",
        opened_at="2026-02-01",
    )
    _create_trade(
        client,
        pid,
        trade_type="assignment",
        strike=20.0,
        expiration="2026-02-20",
        opened_at="2026-02-20",
    )
    _create_trade(
        client,
        pid,
        trade_type="sell_call",
        strike=22.0,
        expiration="2026-03-20",
        opened_at="2026-02-25",
    )
    _create_trade(
        client,
        pid,
        trade_type="called_away",
        strike=22.0,
        expiration="2026-03-20",
        opened_at="2026-03-20",
    )
    return pos


def _trade_close_map(client, position_id):
    """Return {trade_id: closed_at} for every trade on a position."""
    pos = client.get(f"/api/journal/positions/{position_id}").json()
    return {t["id"]: t["closed_at"] for t in pos["trades"]}


def test_reconcile_dry_run_returns_summary_without_writes(client):
    """``dry_run=true`` returns a structured summary and writes nothing."""
    pos = _seed_full_cycle(client)
    pid = pos["id"]

    before_position = client.get(f"/api/journal/positions/{pid}").json()
    before_trade_closes = _trade_close_map(client, pid)

    resp = client.post("/api/journal/reconcile", json={"dry_run": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["positions_processed"] == 1
    assert isinstance(body["per_position"], list)
    assert len(body["per_position"]) == 1
    diff = body["per_position"][0]
    assert diff["ticker"] == "MARA"
    # The recomputer would close the position — preview shows it.
    assert diff["status_after"] == "closed"
    assert diff["shares_after"] == 0

    # No writes: re-query and compare.
    after_position = client.get(f"/api/journal/positions/{pid}").json()
    assert after_position["status"] == before_position["status"]
    assert after_position["shares"] == before_position["shares"]
    assert after_position["broker_cost_basis"] == before_position["broker_cost_basis"]
    after_trade_closes = _trade_close_map(client, pid)
    assert after_trade_closes == before_trade_closes


def test_reconcile_apply_persists_changes(client):
    """``dry_run=false`` commits the recomputed state to the database."""
    pos = _seed_full_cycle(client)
    pid = pos["id"]

    resp = client.post("/api/journal/reconcile", json={"dry_run": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert body["positions_processed"] == 1
    assert body["status_changes"] == 1
    assert body["trades_stamped"] >= 2  # sell_put + sell_call openers stamped

    # Position is now closed at the called_away date.
    after = client.get(f"/api/journal/positions/{pid}").json()
    assert after["status"] == "closed"
    assert after["shares"] == 0
    assert after["closed_at"] == "2026-03-20"

    # Trade.closed_at has been stamped on the openers (issue #136 invariant).
    closed_trade_ids = [t["id"] for t in after["trades"] if t["closed_at"]]
    assert len(closed_trade_ids) >= 2


def test_reconcile_default_is_dry_run(client):
    """Empty body / missing field defaults to ``dry_run=true`` — never mutates."""
    pos = _seed_full_cycle(client)
    pid = pos["id"]

    resp = client.post("/api/journal/reconcile", json={})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True

    after = client.get(f"/api/journal/positions/{pid}").json()
    # Stored state is unchanged from the seed because dry-run is the default.
    assert after["shares"] == 100
    assert after["status"] == "open"


def test_reconcile_empty_journal_returns_zero_counts(client):
    """No positions in DB returns positions_processed=0 with empty diff list."""
    resp = client.post("/api/journal/reconcile", json={"dry_run": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["positions_processed"] == 0
    assert body["per_position"] == []
    assert body["trades_stamped"] == 0
    assert body["errors"] == 0


def test_reconcile_500_does_not_leak_exception_text(client, monkeypatch):
    """If the service raises, the response stays generic — no ``str(e)`` leak."""
    from app.routers import journal as journal_router

    secret = "reconcile-secret-leak-payload"

    def _raise(_db, apply):
        raise RuntimeError(secret)

    monkeypatch.setattr(journal_router, "reconcile_journal_state", _raise)

    resp = client.post("/api/journal/reconcile", json={"dry_run": True})
    assert resp.status_code == 500
    assert secret not in resp.text
    assert resp.json()["detail"] == "An unexpected error occurred"


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


def test_update_position_ignores_strategy_field(client):
    """Issue #131: ``strategy`` is no longer accepted on PositionUpdate.

    The recomputer is authoritative for the displayed label, so a PUT that
    still includes ``strategy`` must succeed (Pydantic ignores unknown
    fields) and the existing strategy must remain unchanged.
    """
    pos = _create_position(client).json()
    resp = client.put(
        f"/api/journal/positions/{pos['id']}", json={"strategy": "wheel"}
    )
    assert resp.status_code == 200
    # Seeded label persists because recomputer was not invoked from PUT.
    assert resp.json()["strategy"] == "csp"
