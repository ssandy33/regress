import json
import logging
from datetime import datetime
from io import StringIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.logging_config import RequestIdFilter, request_id_ctx, setup_logging
from app.models.database import Base, get_db


@pytest.fixture()
def json_log_capture():
    """Set up JSON logging and capture output."""
    stream = StringIO()
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    # Use setup_logging to get the correct formatter, then redirect to our stream
    setup_logging(json_output=True)
    # Steal the formatter from the handler that setup_logging created
    formatter = root.handlers[0].formatter

    root.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(formatter)
    root.addHandler(handler)

    yield stream

    root.handlers = original_handlers
    root.level = original_level


@pytest.fixture()
def app_client():
    """TestClient for middleware tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "test",
        "username": "testuser",
    }
    with patch("app.main.init_db"), \
         patch("app.main.setup_logging"), \
         patch("app.main.create_backup", return_value=""), \
         patch("app.main._run_security_checks"):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


class TestJsonLogging:
    """Tests for JSON log output format."""

    def test_json_output_contains_required_keys(self, json_log_capture):
        logger = logging.getLogger("test.required_keys")
        logger.info("test message")

        output = json_log_capture.getvalue().strip()
        record = json.loads(output)

        assert "timestamp" in record
        assert "level" in record
        assert "module" in record
        assert "message" in record
        assert "request_id" in record

    def test_timestamp_is_iso8601(self, json_log_capture):
        logger = logging.getLogger("test.iso8601")
        logger.info("timestamp check")

        output = json_log_capture.getvalue().strip()
        record = json.loads(output)

        # Should parse without error as ISO 8601
        datetime.fromisoformat(record["timestamp"])

    def test_request_id_propagates_from_context_var(self, json_log_capture):
        token = request_id_ctx.set("test-req-123")
        try:
            logger = logging.getLogger("test.propagation")
            logger.info("propagation test")

            output = json_log_capture.getvalue().strip()
            record = json.loads(output)
            assert record["request_id"] == "test-req-123"
        finally:
            request_id_ctx.reset(token)

    def test_existing_logger_calls_produce_valid_json(self, json_log_capture):
        logger = logging.getLogger("test.existing")
        logger.info("value is %s and count is %d", "foo", 42)

        output = json_log_capture.getvalue().strip()
        record = json.loads(output)
        assert "value is foo and count is 42" in record["message"]

    def test_extra_fields_included_in_json(self, json_log_capture):
        logger = logging.getLogger("test.extras")
        logger.info("with extras", extra={"custom_field": "custom_value"})

        output = json_log_capture.getvalue().strip()
        record = json.loads(output)
        assert record["custom_field"] == "custom_value"


class TestPlainTextLogging:
    """Tests for plain text (non-JSON) logging mode."""

    def test_plain_text_output_is_not_json(self):
        stream = StringIO()
        root = logging.getLogger()
        original_handlers = root.handlers[:]

        try:
            setup_logging(json_output=False)
            formatter = root.handlers[0].formatter

            root.handlers.clear()
            handler = logging.StreamHandler(stream)
            handler.addFilter(RequestIdFilter())
            handler.setFormatter(formatter)
            root.addHandler(handler)

            logger = logging.getLogger("test.plaintext")
            logger.info("plain text message")

            output = stream.getvalue().strip()
            # Should NOT be valid JSON
            with pytest.raises(json.JSONDecodeError):
                json.loads(output)

            # Should contain the message as plain text
            assert "plain text message" in output
        finally:
            root.handlers = original_handlers


class TestRequestLoggingMiddleware:
    """Tests for the request logging middleware."""

    def test_middleware_logs_request_fields(self, app_client, json_log_capture):
        app_client.get("/api/health")

        output = json_log_capture.getvalue().strip()
        # Find the middleware log line (may have multiple lines)
        lines = output.split("\n")
        middleware_line = None
        for line in lines:
            try:
                record = json.loads(line)
                if record.get("method") == "GET" and record.get("path") == "/api/health":
                    middleware_line = record
                    break
            except json.JSONDecodeError:
                continue

        assert middleware_line is not None, f"No middleware log found in: {output}"
        assert middleware_line["method"] == "GET"
        assert middleware_line["path"] == "/api/health"
        assert middleware_line["status_code"] == 200
        assert "duration_ms" in middleware_line
        assert isinstance(middleware_line["duration_ms"], (int, float))
        assert "client_ip" in middleware_line

    def test_custom_request_id_accepted_and_echoed(self, app_client):
        response = app_client.get(
            "/api/health", headers={"X-Request-ID": "custom-id-abc"}
        )
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "custom-id-abc"

    def test_generated_request_id_in_response(self, app_client):
        response = app_client.get("/api/health")
        assert response.status_code == 200
        request_id = response.headers.get("X-Request-ID")
        assert request_id is not None
        assert len(request_id) > 0
        assert request_id != "-"

    def test_malicious_request_id_is_rejected(self, app_client):
        response = app_client.get(
            "/api/health",
            headers={"X-Request-ID": "evil\nX-Injected: true"},
        )
        assert response.status_code == 200
        # Malicious value should be replaced with a generated UUID
        echoed = response.headers["X-Request-ID"]
        assert "\n" not in echoed
        assert "evil" not in echoed

    def test_oversized_request_id_is_rejected(self, app_client):
        response = app_client.get(
            "/api/health",
            headers={"X-Request-ID": "a" * 200},
        )
        assert response.status_code == 200
        echoed = response.headers["X-Request-ID"]
        assert len(echoed) <= 128

    def test_custom_request_id_propagates_to_logs(
        self, app_client, json_log_capture
    ):
        app_client.get(
            "/api/health", headers={"X-Request-ID": "trace-xyz-789"}
        )

        output = json_log_capture.getvalue().strip()
        lines = output.split("\n")
        found = False
        for line in lines:
            try:
                record = json.loads(line)
                if record.get("request_id") == "trace-xyz-789":
                    found = True
                    break
            except json.JSONDecodeError:
                continue

        assert found, f"request_id 'trace-xyz-789' not found in logs: {output}"
