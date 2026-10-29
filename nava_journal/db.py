from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

APP_FOLDER = "NavaJournal"


def default_data_dir() -> Path:
    """Return a writable per-user data folder (never the install directory)."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys_platform_is_macos():
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def sys_platform_is_macos() -> bool:
    import sys
    return sys.platform == "darwin"


def now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection that commits/rolls back like a context manager and always closes."""
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class Database:
    """SQLite storage with explicit schema versions and safe transaction helpers."""

    SCHEMA_VERSION = 5

    def __init__(self, path: str | Path | None = None) -> None:
        # Keep application support data (updater log, status and temporary files)
        # separate from the user-selectable SQLite location.
        self.app_data_dir = default_data_dir()
        self.path = Path(path).expanduser().resolve() if path else self.app_data_dir / "journal.sqlite3"
        self.data_dir = self.path.parent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version < 1:
                self._migration_1(connection)
                connection.execute("PRAGMA user_version = 1")
                current_version = 1
            if current_version < 2:
                self._migration_2(connection)
                connection.execute("PRAGMA user_version = 2")
                current_version = 2
            if current_version < 3:
                self._migration_3(connection)
                connection.execute("PRAGMA user_version = 3")
                current_version = 3
            if current_version < 4:
                self._migration_4(connection)
                connection.execute("PRAGMA user_version = 4")
                current_version = 4
            if current_version < 5:
                self._migration_5(connection)
                connection.execute("PRAGMA user_version = 5")
            # Future schema changes should be added as _migration_6, _migration_7, etc.
            connection.execute("PRAGMA optimize")

    @staticmethod
    def _migration_1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL DEFAULT '#8B7CF6',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                body TEXT NOT NULL DEFAULT '',
                event_date TEXT NOT NULL,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0, 1)),
                is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                display_name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'file' CHECK(kind IN ('file', 'folder')),
                created_at TEXT NOT NULL,
                UNIQUE(entry_id, path)
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL DEFAULT '#38BDF8',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entry_tags (
                entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY(entry_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_entries_event_date ON entries(event_date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_entries_category_id ON entries(category_id);
            CREATE INDEX IF NOT EXISTS idx_entries_favorite ON entries(is_favorite);
            CREATE INDEX IF NOT EXISTS idx_attachments_entry_id ON attachments(entry_id);
            CREATE INDEX IF NOT EXISTS idx_entry_tags_tag_id ON entry_tags(tag_id);
            """
        )
        now = now_local_iso()
        for name, color in (
            ("شخصی", "#8B7CF6"),
            ("کار", "#38BDF8"),
            ("مالی", "#34D399"),
            ("خانواده", "#F59E0B"),
            ("فناوری", "#F472B6"),
            ("بدون دسته", "#94A3B8"),
        ):
            connection.execute(
                "INSERT OR IGNORE INTO categories(name, color, created_at) VALUES (?, ?, ?)",
                (name, color, now),
            )


    @staticmethod
    def _migration_2(connection: sqlite3.Connection) -> None:
        """Add optional people records and link each journal entry to one person.

        This migration is intentionally additive: existing entries, attachments,
        categories, tags and settings remain untouched.
        """
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                notes TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#38BDF8',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_people_name ON people(name);
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)").fetchall()}
        if "person_id" not in columns:
            connection.execute(
                "ALTER TABLE entries ADD COLUMN person_id INTEGER REFERENCES people(id) ON DELETE SET NULL"
            )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_entries_person_id ON entries(person_id)")


    @staticmethod
    def _migration_3(connection: sqlite3.Connection) -> None:
        """Persist full Jalali date alongside canonical Gregorian ISO date."""
        columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)").fetchall()}
        if "event_jalali_date" not in columns:
            connection.execute("ALTER TABLE entries ADD COLUMN event_jalali_date TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_event_jalali_date ON entries(event_jalali_date DESC, id DESC)"
        )

    @staticmethod
    def _migration_4(connection: sqlite3.Connection) -> None:
        """Add optional importance and follow-up tracking without rewriting records."""
        columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)").fetchall()}
        if "importance" not in columns:
            connection.execute(
                "ALTER TABLE entries ADD COLUMN importance TEXT NOT NULL DEFAULT 'normal' "
                "CHECK(importance IN ('normal', 'important', 'critical'))"
            )
        if "follow_up_status" not in columns:
            connection.execute(
                "ALTER TABLE entries ADD COLUMN follow_up_status TEXT NOT NULL DEFAULT 'none' "
                "CHECK(follow_up_status IN ('none', 'pending', 'in_progress', 'done'))"
            )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_entries_follow_up_status ON entries(follow_up_status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_entries_importance ON entries(importance)")

    @staticmethod
    def _migration_5(connection: sqlite3.Connection) -> None:
        """Add an optional per-attachment note while retaining every attachment.

        The IF NOT EXISTS guard also repairs incomplete legacy/test databases where
        the attachments table was omitted even though the user_version was advanced.
        """
        connection.execute(
            """CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                display_name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'file' CHECK(kind IN ('file', 'folder')),
                created_at TEXT NOT NULL,
                UNIQUE(entry_id, path)
            )"""
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(attachments)").fetchall()}
        if "notes" not in columns:
            connection.execute("ALTER TABLE attachments ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_attachments_entry_id ON attachments(entry_id)")

    def move_to_and_switch(self, destination: str | Path, overwrite: bool = False) -> Path:
        """Move the active SQLite database to a new path and switch to it.

        SQLite WAL data is checkpointed and the database is put into DELETE journal
        mode before the filesystem move. The destination is opened and verified
        before success is returned. If anything fails, the source path is restored.
        Existing destination data (when explicitly allowed) is preserved separately.
        """
        import shutil

        target = Path(destination).expanduser().resolve()
        source = self.path.resolve()
        if target == source:
            raise ValueError("مسیر انتخاب‌شده همان مسیر فعلی پایگاه داده است.")
        if target.suffix.lower() not in {".sqlite3", ".db", ".sqlite"}:
            raise ValueError("پسوند فایل باید .sqlite3، .sqlite یا .db باشد.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError("فایل مقصد از قبل وجود دارد؛ برای جایگزینی باید تأیید شود.")

        original_schema_version = self.schema_version()
        preserved_target: Path | None = None
        preserved_sidecars: list[tuple[Path, Path]] = []
        source_moved = False
        move_started = False

        def sidecar(path: Path, suffix: str) -> Path:
            return Path(str(path) + suffix)

        def make_portable(path: Path) -> None:
            """Flush WAL and release SQLite file handles before moving a database."""
            if not path.is_file():
                raise FileNotFoundError(f"فایل پایگاه داده پیدا نشد: {path}")
            connection = sqlite3.connect(path, timeout=15)
            try:
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint and int(checkpoint[0]) != 0:
                    raise sqlite3.OperationalError("پایگاه داده هنوز در حال استفاده است؛ همه پنجره‌های روزنگار را ببند.")
                journal_mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
                if journal_mode != "delete":
                    raise sqlite3.OperationalError("تبدیل ایمن پایگاه داده برای انتقال انجام نشد.")
            finally:
                connection.close()
            # These sidecars are no longer authoritative after a successful checkpoint
            # and DELETE-journal switch. Remove stale files so they cannot attach to a
            # different database later.
            for suffix in ("-wal", "-shm"):
                extra = sidecar(path, suffix)
                if extra.exists():
                    extra.unlink()

        def reserve_existing_target() -> None:
            nonlocal preserved_target, preserved_sidecars
            if not target.exists():
                return
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            preserved_target = target.with_name(f"{target.stem}.replaced_{stamp}{target.suffix}")
            counter = 1
            while preserved_target.exists():
                preserved_target = target.with_name(f"{target.stem}.replaced_{stamp}_{counter}{target.suffix}")
                counter += 1
            os.replace(target, preserved_target)
            for suffix in ("-wal", "-shm"):
                old_extra = sidecar(target, suffix)
                if old_extra.exists():
                    new_extra = sidecar(preserved_target, suffix)
                    os.replace(old_extra, new_extra)
                    preserved_sidecars.append((new_extra, old_extra))

        def restore_reserved_target() -> None:
            if preserved_target is not None and preserved_target.exists() and not target.exists():
                os.replace(preserved_target, target)
            for old_extra, target_extra in preserved_sidecars:
                if old_extra.exists() and not target_extra.exists():
                    os.replace(old_extra, target_extra)

        try:
            # This operation is intentionally a move, not a permanent copy. On a
            # different drive, shutil.move performs the OS-required copy/delete move.
            make_portable(source)
            reserve_existing_target()
            move_started = True
            shutil.move(str(source), str(target))
            source_moved = not source.exists() and target.is_file()
            if not source_moved:
                raise OSError("انتقال فایل کامل نشد؛ فایل مبدأ همچنان در مسیر قبلی قرار دارد.")

            self.path = target
            self.data_dir = target.parent
            self.initialize()
            check = self.quick_check()
            if check != "ok":
                raise sqlite3.DatabaseError(f"بررسی سلامت فایل منتقل‌شده ناموفق بود: {check}")
            if self.schema_version() != original_schema_version:
                raise sqlite3.DatabaseError("نسخه ساختار پایگاه داده پس از انتقال تغییر کرده است.")
            return target
        except Exception as exc:
            # Roll back to the old live path if the destination move or verification
            # fails. The original destination (if any) is restored as well.
            try:
                if target.exists() and source_moved:
                    make_portable(target)
                    if not source.exists():
                        shutil.move(str(target), str(source))
                elif move_started and target.exists() and source.exists() and target != source:
                    # A cross-volume move can leave a partial destination if the copy
                    # phase fails; the intact source remains authoritative.
                    target.unlink(missing_ok=True)
                    for suffix in ("-wal", "-shm"):
                        sidecar(target, suffix).unlink(missing_ok=True)
            except Exception:
                # Preserve the original exception; the user-facing message tells the
                # user to inspect both paths if the OS also blocks rollback.
                pass
            self.path = source
            self.data_dir = source.parent
            try:
                if source.exists():
                    self.initialize()
            except Exception:
                pass
            try:
                restore_reserved_target()
            except Exception:
                pass
            raise RuntimeError(
                f"انتقال پایگاه داده کامل نشد و مسیر قبلی حفظ شد.\nجزئیات: {exc}"
            ) from exc

    def copy_to_and_switch(self, destination: str | Path, overwrite: bool = False) -> Path:
        """Backward-compatible name; semantics now match the user's requested move."""
        return self.move_to_and_switch(destination, overwrite=overwrite)

    def backup_to(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() == self.path.resolve():
            raise ValueError("Backup destination must be different from the live database.")
        with self.connect() as source, sqlite3.connect(target, factory=_ClosingConnection) as backup:
            source.backup(backup)
        return target

    def quick_check(self) -> str:
        with self.connect() as connection:
            return str(connection.execute("PRAGMA quick_check").fetchone()[0])

    def schema_version(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
