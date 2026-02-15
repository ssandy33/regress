import pytest
from pathlib import Path

from app.services.backup import ensure_backup_dir, list_backups, BACKUP_DIR


class TestBackup:
    def test_ensure_backup_dir_creates_directory(self):
        """ensure_backup_dir should create the directory and return its path."""
        result = ensure_backup_dir()
        assert result == BACKUP_DIR
        assert BACKUP_DIR.is_dir()

    def test_list_backups_returns_list(self):
        """list_backups should return a list (possibly empty)."""
        result = list_backups()
        assert isinstance(result, list)
        for entry in result:
            assert "filename" in entry
            assert "size_bytes" in entry
            assert "created_at" in entry
