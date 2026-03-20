from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class CacheEntry(Base):
    __tablename__ = "cache"

    asset_key = Column(String, primary_key=True)  # e.g. "schwab:AAPL", "fred:DGS10"
    data = Column(Text, nullable=False)  # JSON-serialized DataFrame
    fetched_at = Column(String, nullable=False)  # ISO datetime
    source_frequency = Column(String, nullable=False)  # daily / monthly / quarterly
    source_name = Column(String, nullable=False)  # schwab / fred / zillow


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


class Position(Base):
    __tablename__ = "positions"

    id = Column(String, primary_key=True)  # UUID4
    ticker = Column(String, nullable=False)
    shares = Column(Integer, nullable=False, default=100)
    broker_cost_basis = Column(Float, nullable=False)  # total dollar cost for all shares
    status = Column(String, nullable=False, default="open")  # "open" | "closed"
    strategy = Column(String, nullable=False)  # "csp" | "cc" | "wheel"
    opened_at = Column(String, nullable=False)  # ISO datetime
    closed_at = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    trades = relationship(
        "Trade",
        back_populates="position",
        order_by="Trade.opened_at",
        cascade="all, delete-orphan",
    )


class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True)  # UUID4
    position_id = Column(String, ForeignKey("positions.id"), nullable=False)
    trade_type = Column(String, nullable=False)  # "sell_put" | "buy_put_close" | "assignment" | "sell_call" | "buy_call_close" | "called_away"
    strike = Column(Float, nullable=False)
    expiration = Column(String, nullable=False)  # date string
    premium = Column(Float, nullable=False)  # per-share, positive for credits, negative for debits
    fees = Column(Float, default=0.0)
    quantity = Column(Integer, default=1)  # number of contracts
    opened_at = Column(String, nullable=False)  # ISO datetime
    closed_at = Column(String, nullable=True)
    close_reason = Column(String, nullable=True)  # "fifty_pct_target" | "full_expiration" | "rolled" | "closed_early" | "assigned" | "called_away"
    position = relationship("Position", back_populates="trades")


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
