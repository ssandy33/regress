from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fred_api_key: str = ""
    schwab_app_key: str = ""
    schwab_app_secret: str = ""
    alpha_vantage_api_key: str = ""
    nextauth_secret: str = ""
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


def get_schwab_credentials() -> tuple[str, str]:
    """Get Schwab app key and secret, checking DB settings as fallback."""
    app_key = settings.schwab_app_key
    app_secret = settings.schwab_app_secret
    if app_key and app_secret:
        return app_key, app_secret
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            key_entry = db.query(AppSetting).filter(AppSetting.key == "schwab_app_key").first()
            secret_entry = db.query(AppSetting).filter(AppSetting.key == "schwab_app_secret").first()
            if key_entry:
                app_key = key_entry.value
            if secret_entry:
                app_secret = secret_entry.value
        finally:
            db.close()
    except Exception:
        pass
    return app_key, app_secret
