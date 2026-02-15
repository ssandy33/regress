from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.database import CacheEntry


class CacheService:
    def __init__(self, db: DBSession):
        self.db = db

    def get(self, asset_key: str) -> dict | None:
        """Return cached data only if fresh."""
        entry = self.db.query(CacheEntry).filter(
            CacheEntry.asset_key == asset_key
        ).first()
        if entry is None:
            return None

        if not self._is_fresh(entry):
            return None

        return {
            "data": entry.data,
            "fetched_at": entry.fetched_at,
            "source_frequency": entry.source_frequency,
            "source_name": entry.source_name,
        }

    def get_stale(self, asset_key: str) -> dict | None:
        """Return cached data regardless of freshness."""
        entry = self.db.query(CacheEntry).filter(
            CacheEntry.asset_key == asset_key
        ).first()
        if entry is None:
            return None

        return {
            "data": entry.data,
            "fetched_at": entry.fetched_at,
            "source_frequency": entry.source_frequency,
            "source_name": entry.source_name,
        }

    def set(self, asset_key: str, data: str, frequency: str, source: str) -> None:
        """Upsert a cache entry."""
        now = datetime.now(timezone.utc).isoformat()
        entry = self.db.query(CacheEntry).filter(
            CacheEntry.asset_key == asset_key
        ).first()

        if entry:
            entry.data = data
            entry.fetched_at = now
            entry.source_frequency = frequency
            entry.source_name = source
        else:
            entry = CacheEntry(
                asset_key=asset_key,
                data=data,
                fetched_at=now,
                source_frequency=frequency,
                source_name=source,
            )
            self.db.add(entry)

        self.db.commit()

    def _is_fresh(self, entry: CacheEntry) -> bool:
        fetched_at = datetime.fromisoformat(entry.fetched_at)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - fetched_at

        if entry.source_frequency == "daily":
            return age < timedelta(hours=settings.cache_ttl_daily_hours)
        else:  # monthly, quarterly
            return age < timedelta(days=settings.cache_ttl_monthly_days)
