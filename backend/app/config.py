from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fred_api_key: str = ""
    database_url: str = "sqlite:///./regression_tool.db"
    cache_ttl_daily_hours: int = 24
    cache_ttl_monthly_days: int = 7
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


def get_fred_api_key() -> str:
    """Get FRED API key, checking DB settings as fallback."""
    if settings.fred_api_key:
        return settings.fred_api_key
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            entry = db.query(AppSetting).filter(AppSetting.key == "fred_api_key").first()
            if entry:
                return entry.value
        finally:
            db.close()
    except Exception:
        pass
    return ""
