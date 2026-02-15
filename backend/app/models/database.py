from sqlalchemy import Column, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class CacheEntry(Base):
    __tablename__ = "cache"

    asset_key = Column(String, primary_key=True)  # e.g. "yfinance:AAPL", "fred:DGS10"
    data = Column(Text, nullable=False)  # JSON-serialized DataFrame
    fetched_at = Column(String, nullable=False)  # ISO datetime
    source_frequency = Column(String, nullable=False)  # daily / monthly / quarterly
    source_name = Column(String, nullable=False)  # yfinance / fred / zillow


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)  # UUID4
    name = Column(String, nullable=False)
    config = Column(Text, nullable=False)  # JSON: regression type, parameters
    results = Column(Text, nullable=True)  # JSON: regression output
    created_at = Column(String, nullable=False)  # ISO datetime
    updated_at = Column(String, nullable=False)  # ISO datetime


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
