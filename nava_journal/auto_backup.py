"""Automatic, non-destructive SQLite snapshot backups on application shutdown."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import Database

BACKUP_FOLDER_NAME = "NavaJournal_AutoBackups"


def application_root() -> Path:
    """Return the folder containing the installed app or the source project."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def preferred_backup_folder(root: str | Path | None = None) -> Path:
    """The visible backup directory beside the main application files."""
    return Path(root).expanduser().resolve() / BACKUP_FOLDER_NAME if root else application_root() / BACKUP_FOLDER_NAME


def _jalali_date_label(gregorian_date: str) -> str:
    # Import lazily so the snapshot mechanism itself remains unit-testable even
    # in build environments that have not installed the app requirements yet.
    from .jalali import format_jalali
    return format_jalali(gregorian_date, separator=".", short_year=False)


def _unique_target(folder: Path, now: datetime) -> Path:
    jalali_date = _jalali_date_label(now.date().isoformat())
    stem = f"NavaJournal_AutoBackup_{jalali_date}_{now:%H-%M-%S}"
    target = folder / f"{stem}.sqlite3"
    suffix = 2
    while target.exists():
        target = folder / f"{stem}_{suffix:02d}.sqlite3"
        suffix += 1
    return target


def _make_and_verify(database: "Database", target: Path) -> Path:
    """Use SQLite's online backup API and verify the snapshot, never file-copy a live DB."""
    try:
        database.backup_to(target)
        with sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as connection:
            result = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            if result.lower() != "ok":
                raise sqlite3.DatabaseError(f"Backup quick_check returned: {result}")
            # A structural query verifies that this is a readable journal database.
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        if target.stat().st_size <= 0:
            raise OSError("The backup file is empty.")
        return target
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def create_close_backup(
    database: "Database",
    root: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[Path, bool]:
    """Create one timestamped snapshot when the app closes.

    Returns (backup_path, used_fallback_location). Existing backups are never
    overwritten or removed. The source database is accessed only through SQLite's
    online-backup API; its file and any existing snapshots are not renamed or deleted.
    If the installation directory is read-only, a per-user fallback is used.
    """
    captured_at = now or datetime.now().astimezone()
    primary = preferred_backup_folder(root)
    fallback = Path(database.app_data_dir) / BACKUP_FOLDER_NAME
    candidates: list[tuple[Path, bool]] = [(primary, False)]
    if fallback.resolve() != primary.resolve():
        candidates.append((fallback, True))

    errors: list[str] = []
    for folder, used_fallback in candidates:
        target: Path | None = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = _unique_target(folder, captured_at)
            result = _make_and_verify(database, target)
            return result, used_fallback
        except Exception as exc:
            errors.append(f"{folder}: {exc}")
            if target is not None:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass

    raise OSError("پشتیبان خودکار ساخته نشد. جزئیات:\n" + "\n".join(errors))
