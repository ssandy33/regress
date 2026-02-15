import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "backups"
MAX_BACKUPS = 5


def _get_db_path() -> Path:
    """Extract the file path from the SQLite URL."""
    url = settings.database_url
    # "sqlite:///./regression_tool.db" -> "./regression_tool.db"
    path_str = url.replace("sqlite:///", "")
    return Path(path_str).resolve()


def ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def create_backup() -> str:
    """Copy current DB to backups dir. Returns backup filename."""
    db_path = _get_db_path()
    if not db_path.exists():
        logger.info("No database file to backup yet")
        return ""

    ensure_backup_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"regression_tool_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name

    shutil.copy2(str(db_path), str(backup_path))
    logger.info(f"Backup created: {backup_name}")

    # Prune old backups, keep MAX_BACKUPS most recent
    backups = sorted(
        BACKUP_DIR.glob("regression_tool_*.db"),
        key=os.path.getmtime,
        reverse=True,
    )
    for old in backups[MAX_BACKUPS:]:
        old.unlink()
        logger.info(f"Pruned old backup: {old.name}")

    return backup_name


def list_backups() -> list[dict]:
    """Return list of available backups with metadata."""
    ensure_backup_dir()
    backups = sorted(
        BACKUP_DIR.glob("regression_tool_*.db"),
        key=os.path.getmtime,
        reverse=True,
    )
    result = []
    for b in backups:
        stat = b.stat()
        result.append({
            "filename": b.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return result


def restore_backup(filename: str) -> None:
    """Restore a backup by copying it over the current DB. Live swap, no restart."""
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup '{filename}' not found")

    # Prevent path traversal
    if not str(backup_path.resolve()).startswith(str(BACKUP_DIR.resolve())):
        raise ValueError("Invalid backup path")

    db_path = _get_db_path()

    # Close all SQLAlchemy connections, copy, reinitialize
    from app.models.database import engine, init_db

    engine.dispose()
    shutil.copy2(str(backup_path), str(db_path))
    init_db()
    logger.info(f"Restored from backup: {filename}")
