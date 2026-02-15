class TestSessionsCRUD:
    def test_create_session(self, client):
        payload = {"name": "Test Session", "config": {"type": "linear", "asset": "AAPL"}}
        response = client.post("/api/sessions", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Session"
        assert "id" in data
        assert data["config"]["type"] == "linear"

    def test_list_sessions_empty(self, client):
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json()["sessions"] == []

    def test_list_sessions_after_create(self, client):
        client.post("/api/sessions", json={"name": "S1", "config": {}})
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert len(response.json()["sessions"]) == 1

    def test_get_session_by_id(self, client):
        create_resp = client.post("/api/sessions", json={"name": "S1", "config": {"x": 1}})
        session_id = create_resp.json()["id"]
        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 200
        assert response.json()["id"] == session_id
        assert response.json()["config"]["x"] == 1

    def test_get_session_not_found(self, client):
        response = client.get("/api/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_delete_session(self, client):
        create_resp = client.post("/api/sessions", json={"name": "S1", "config": {}})
        session_id = create_resp.json()["id"]
        delete_resp = client.delete(f"/api/sessions/{session_id}")
        assert delete_resp.status_code == 204
        get_resp = client.get(f"/api/sessions/{session_id}")
        assert get_resp.status_code == 404

    def test_delete_session_not_found(self, client):
        response = client.delete("/api/sessions/nonexistent-id")
        assert response.status_code == 404
