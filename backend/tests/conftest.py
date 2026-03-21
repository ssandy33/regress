import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from app.auth import get_current_user
from app.logging_config import setup_logging
from app.models.database import Base, get_db
from app.models.schemas import DataMeta, DateRange
from app.services.data_fetcher import DataFetcher


@pytest.fixture(autouse=True, scope="session")
def _configure_test_logging():
    """Use plain text logging in tests for readable output."""
    setup_logging(json_output=False)


def _make_price_df(seed=42, n=60):
    """Create a realistic daily price DataFrame."""
    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    prices = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))
    df = pd.DataFrame({"value": prices}, index=dates)
    df.index.name = "date"
    return df


def _make_meta(n=60):
    return DataMeta(
        source="schwab",
        frequency="daily",
        fetched_at="2024-06-01T00:00:00+00:00",
        is_stale=False,
        record_count=n,
        date_range=DateRange(start="2023-01-01", end="2023-03-01"),
    )


@pytest.fixture()
def client():
    """TestClient with in-memory DB and patched lifespan."""
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
    # Bypass auth for integration tests — auth logic is tested separately
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test", "username": "testuser"}
    with patch("app.main.init_db"), \
         patch("app.main.setup_logging"), \
         patch("app.main.create_backup", return_value=""), \
         patch("app.main._run_security_checks"):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def mock_fetcher():
    """Patch DataFetcher.fetch to return a single mock price series."""
    df = _make_price_df(seed=42, n=60)
    meta = _make_meta(n=60)
    with patch.object(DataFetcher, "fetch", return_value=(df, meta)):
        yield


@pytest.fixture()
def multi_asset_fetcher():
    """Patch DataFetcher.fetch to return different data per call."""
    call_count = 0

    def _side_effect(identifier, start, end):
        nonlocal call_count
        call_count += 1
        return _make_price_df(seed=call_count * 10, n=60), _make_meta()

    with patch.object(DataFetcher, "fetch", side_effect=_side_effect):
        yield
