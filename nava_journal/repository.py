from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .db import Database, now_local_iso
from .jalali import JalaliDate

DEMO_SEED_SETTING_KEY = "nava/demo_data/seed_v1"


class JournalRepository:
    """SQL/data layer. UI classes never write SQL directly."""

    def __init__(self, database: Database) -> None:
        self.db = database
        self._backfill_full_jalali_dates()

    @staticmethod
    def _jalali_from_gregorian_iso(event_date: str) -> str | None:
        """Convert a stored Gregorian ISO date to a full Jalali ISO-like date."""
        try:
            from persiantools.jdatetime import JalaliDate
        except ImportError:
            # The desktop app installs PersianTools; keeping this optional makes the
            # SQLite repository tests usable in a minimal Python environment too.
            return None
        value = JalaliDate(date.fromisoformat(event_date[:10]))
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"

    @staticmethod
    def _validate_jalali_storage_date(value: str, event_date: str) -> str:
        pieces = value.strip().replace(".", "-").replace("/", "-").split("-")
        if len(pieces) != 3 or not all(piece.isdigit() for piece in pieces):
            raise ValueError("تاریخ شمسی باید به شکل سال-ماه-روز باشد.")
        year, month, day = (int(piece) for piece in pieces)
        if year < 1 or not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError("تاریخ شمسی واردشده معتبر نیست.")
        normalized = f"{year:04d}-{month:02d}-{day:02d}"
        try:
            from persiantools.jdatetime import JalaliDate
            converted = JalaliDate(year, month, day).to_gregorian().isoformat()
            if converted != event_date[:10]:
                raise ValueError("تاریخ شمسی و تاریخ استاندارد با هم مطابقت ندارند.")
        except ImportError:
            pass
        return normalized

    def demo_data_status(self) -> dict[str, Any]:
        """Report the optional fictional-data pack without scanning or changing user data."""
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (DEMO_SEED_SETTING_KEY,)
            ).fetchone()
            if row is None:
                return {"seeded": False, "count": 0}
            try:
                manifest = json.loads(str(row["value"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                manifest = {}
            ids = [int(value) for value in manifest.get("entry_ids", []) if str(value).isdigit()]
            count = 0
            if ids:
                placeholders = ",".join("?" for _ in ids)
                count = int(connection.execute(
                    f"SELECT COUNT(*) FROM entries WHERE id IN ({placeholders})", ids
                ).fetchone()[0])
            return {"seeded": True, "count": count}

    def seed_demo_data(self) -> dict[str, Any]:
        """Insert 50 fictional Persian entries and keep an exact undo manifest.

        The records are added to the currently active database. Existing journal rows
        are never updated, and any references created exclusively for this pack are
        removed only if they are still unused when the pack is cleared.
        """
        from .demo_data import DEMO_CATEGORIES, DEMO_ENTRIES, DEMO_PEOPLE, DEMO_TAGS
        import secrets

        now_dt = datetime.now().astimezone()
        today = now_dt.date()
        attachment_root = self.db.app_data_dir / "demo_attachments"
        batch = secrets.token_hex(4)
        created_files: list[str] = []
        entry_ids: list[int] = []
        created_person_ids: list[int] = []
        created_tag_ids: list[int] = []
        created_category_ids: list[int] = []

        def timestamp_for(day: date, hour: int, minute: int) -> str:
            moment = datetime.combine(day, time(hour=hour, minute=minute)).astimezone()
            if moment > now_dt:
                moment = now_dt
            return moment.isoformat(timespec="seconds")

        try:
            with self.db.connect() as connection:
                existing_pack = connection.execute(
                    "SELECT value FROM app_settings WHERE key = ?", (DEMO_SEED_SETTING_KEY,)
                ).fetchone()
                if existing_pack is not None:
                    try:
                        old = json.loads(str(existing_pack["value"] or "{}"))
                        ids = [int(value) for value in old.get("entry_ids", []) if str(value).isdigit()]
                    except (TypeError, ValueError, json.JSONDecodeError):
                        ids = []
                    count = 0
                    if ids:
                        placeholders = ",".join("?" for _ in ids)
                        count = int(connection.execute(
                            f"SELECT COUNT(*) FROM entries WHERE id IN ({placeholders})", ids
                        ).fetchone()[0])
                    return {"created": 0, "count": count, "already_seeded": True}

                category_ids: dict[str, int] = {}
                for name, color in DEMO_CATEGORIES:
                    row = connection.execute(
                        "SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (name,)
                    ).fetchone()
                    if row is None:
                        cursor = connection.execute(
                            "INSERT INTO categories(name, color, created_at) VALUES (?, ?, ?)",
                            (name, color, now_local_iso()),
                        )
                        category_id = int(cursor.lastrowid)
                        created_category_ids.append(category_id)
                    else:
                        category_id = int(row["id"])
                    category_ids[name] = category_id

                people_ids: dict[str, int] = {}
                for name, notes, color in DEMO_PEOPLE:
                    row = connection.execute(
                        "SELECT id FROM people WHERE name = ? COLLATE NOCASE", (name,)
                    ).fetchone()
                    if row is None:
                        stamp = now_local_iso()
                        cursor = connection.execute(
                            "INSERT INTO people(name, notes, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                            (name, notes, color, stamp, stamp),
                        )
                        person_id = int(cursor.lastrowid)
                        created_person_ids.append(person_id)
                    else:
                        person_id = int(row["id"])
                    people_ids[name] = person_id

                tag_ids: dict[str, int] = {}
                for name, color in DEMO_TAGS:
                    row = connection.execute(
                        "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
                    ).fetchone()
                    if row is None:
                        cursor = connection.execute(
                            "INSERT INTO tags(name, color, created_at) VALUES (?, ?, ?)",
                            (name, color, now_local_iso()),
                        )
                        tag_id = int(cursor.lastrowid)
                        created_tag_ids.append(tag_id)
                    else:
                        tag_id = int(row["id"])
                    tag_ids[name] = tag_id

                attachment_root.mkdir(parents=True, exist_ok=True)
                for index, blueprint in enumerate(DEMO_ENTRIES, start=1):
                    days_ago = max(0, min(730, int(blueprint["days_ago"])))
                    event_day = today - timedelta(days=days_ago)
                    event_iso = event_day.isoformat()
                    jalali = JalaliDate(event_day)
                    jalali_iso = f"{jalali.year:04d}-{jalali.month:02d}-{jalali.day:02d}"
                    delay = min(index % 5, days_ago)
                    created_day = min(today, event_day + timedelta(days=delay))
                    updated_day = min(today, created_day + timedelta(days=(index * 3) % 12))
                    created_at = timestamp_for(created_day, 8 + (index * 7) % 12, (index * 13) % 60)
                    updated_at = timestamp_for(updated_day, 9 + (index * 5) % 10, (index * 17) % 60)
                    person_name = str(blueprint.get("person") or "")
                    person_id = people_ids.get(person_name) if person_name else None
                    category_id = category_ids.get(str(blueprint["category"]))
                    cursor = connection.execute(
                        """INSERT INTO entries
                           (title, body, event_date, event_jalali_date, category_id, person_id,
                            is_favorite, is_archived, importance, follow_up_status, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(blueprint["title"]), str(blueprint["body"]), event_iso, jalali_iso,
                            category_id, person_id, int(bool(blueprint.get("favorite"))),
                            int(bool(blueprint.get("archived"))), str(blueprint.get("importance") or "normal"),
                            str(blueprint.get("follow_up") or "none"), created_at, updated_at,
                        ),
                    )
                    entry_id = int(cursor.lastrowid)
                    entry_ids.append(entry_id)
                    # Every generated record gets a shared marker tag so the user can
                    # search for the entire pack and identify it in advanced filters.
                    for tag_name in [*blueprint.get("tags", []), "داده آزمایشی"]:
                        tag_id = tag_ids.get(str(tag_name))
                        if tag_id is not None:
                            connection.execute(
                                "INSERT OR IGNORE INTO entry_tags(entry_id, tag_id) VALUES (?, ?)",
                                (entry_id, tag_id),
                            )

                    for attachment_index, attachment in enumerate(blueprint.get("attachments", []), start=1):
                        path = attachment_root / f"nava_demo_{batch}_{index:02d}_{attachment_index:02d}.txt"
                        content = (
                            "روزنگار · فایل متنی آزمایشی\n"
                            f"عنوان رویداد: {blueprint['title']}\n"
                            f"تاریخ رویداد: {jalali_iso}\n\n"
                            f"{blueprint['body']}\n\n"
                            f"یادداشت پیوست: {attachment.get('note', '')}\n"
                        )
                        path.write_text(content, encoding="utf-8")
                        created_files.append(str(path))
                        connection.execute(
                            """INSERT INTO attachments
                               (entry_id, path, display_name, kind, notes, created_at)
                               VALUES (?, ?, ?, 'file', ?, ?)""",
                            (
                                entry_id, str(path), str(attachment.get("name") or path.name),
                                str(attachment.get("note") or ""), created_at,
                            ),
                        )

                manifest = {
                    "pack": "Nava Journal fictional Persian demo data",
                    "version": 1,
                    "entry_ids": entry_ids,
                    "created_person_ids": created_person_ids,
                    "created_tag_ids": created_tag_ids,
                    "created_category_ids": created_category_ids,
                    "attachment_paths": created_files,
                }
                connection.execute(
                    "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)",
                    (DEMO_SEED_SETTING_KEY, json.dumps(manifest, ensure_ascii=False), now_local_iso()),
                )
        except Exception:
            for path in created_files:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return {"created": len(entry_ids), "count": len(entry_ids), "already_seeded": False}

    def clear_demo_data(self) -> dict[str, Any]:
        """Remove only the exact rows and attachment files created by seed_demo_data."""
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (DEMO_SEED_SETTING_KEY,)
            ).fetchone()
            if row is None:
                return {"removed": 0, "files_removed": 0}
            try:
                manifest = json.loads(str(row["value"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                manifest = {}
            entry_ids = [int(value) for value in manifest.get("entry_ids", []) if str(value).isdigit()]
            file_paths = [str(value) for value in manifest.get("attachment_paths", []) if value]
            tag_ids = [int(value) for value in manifest.get("created_tag_ids", []) if str(value).isdigit()]
            person_ids = [int(value) for value in manifest.get("created_person_ids", []) if str(value).isdigit()]
            category_ids = [int(value) for value in manifest.get("created_category_ids", []) if str(value).isdigit()]
            removed = 0
            if entry_ids:
                placeholders = ",".join("?" for _ in entry_ids)
                removed = int(connection.execute(
                    f"DELETE FROM entries WHERE id IN ({placeholders})", entry_ids
                ).rowcount)
            # Remove only seed-created references, and only if no remaining user record uses them.
            for tag_id in tag_ids:
                connection.execute(
                    "DELETE FROM tags WHERE id = ? AND NOT EXISTS (SELECT 1 FROM entry_tags WHERE tag_id = ?)",
                    (tag_id, tag_id),
                )
            for person_id in person_ids:
                connection.execute(
                    "DELETE FROM people WHERE id = ? AND NOT EXISTS (SELECT 1 FROM entries WHERE person_id = ?)",
                    (person_id, person_id),
                )
            for category_id in category_ids:
                connection.execute(
                    "DELETE FROM categories WHERE id = ? AND NOT EXISTS (SELECT 1 FROM entries WHERE category_id = ?)",
                    (category_id, category_id),
                )
            connection.execute("DELETE FROM app_settings WHERE key = ?", (DEMO_SEED_SETTING_KEY,))

        files_removed = 0
        trusted_root = (self.db.app_data_dir / "demo_attachments").resolve()
        for raw_path in file_paths:
            try:
                path = Path(raw_path).resolve()
                # Defensive path validation: never unlink outside the dedicated demo folder.
                if path.parent == trusted_root and path.name.startswith("nava_demo_") and path.is_file():
                    path.unlink()
                    files_removed += 1
            except OSError:
                pass
        return {"removed": removed, "files_removed": files_removed}

    def _backfill_full_jalali_dates(self) -> None:
        """Populate the new field for existing records when PersianTools is available."""
        try:
            from persiantools.jdatetime import JalaliDate
        except ImportError:
            return
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id, event_date FROM entries WHERE event_jalali_date IS NULL OR event_jalali_date = ''"
            ).fetchall()
            for row in rows:
                try:
                    value = JalaliDate(date.fromisoformat(str(row["event_date"])[:10]))
                except (ValueError, TypeError):
                    continue
                jalali_iso = f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
                connection.execute(
                    "UPDATE entries SET event_jalali_date = ? WHERE id = ?",
                    (jalali_iso, int(row["id"])),
                )

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------
    def categories(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, color, created_at FROM categories ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def add_category(self, name: str, color: str = "#8B7CF6") -> int:
        clean = name.strip()
        if not clean:
            raise ValueError("نام دسته‌بندی نمی‌تواند خالی باشد.")
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO categories(name, color, created_at) VALUES (?, ?, ?)",
                (clean, color, now_local_iso()),
            )
            return int(cursor.lastrowid)

    def update_category(self, category_id: int, name: str, color: str = "#8B7CF6") -> None:
        clean = name.strip()
        if not clean:
            raise ValueError("نام دسته‌بندی نمی‌تواند خالی باشد.")
        with self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE categories SET name = ?, color = ? WHERE id = ?",
                (clean, color, int(category_id)),
            )
            if cursor.rowcount == 0:
                raise ValueError("دسته‌بندی پیدا نشد.")

    def delete_category(self, category_id: int) -> None:
        # Existing journal entries are preserved; their category becomes NULL.
        with self.db.connect() as connection:
            connection.execute("DELETE FROM categories WHERE id = ?", (int(category_id),))

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------
    def people(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, notes, color, created_at, updated_at FROM people ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def add_person(self, name: str, notes: str = "", color: str = "#38BDF8") -> int:
        clean = name.strip()
        if not clean:
            raise ValueError("نام شخص نمی‌تواند خالی باشد.")
        now = now_local_iso()
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO people(name, notes, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (clean, notes.strip(), color, now, now),
            )
            return int(cursor.lastrowid)

    def update_person(self, person_id: int, name: str, notes: str = "", color: str = "#38BDF8") -> None:
        clean = name.strip()
        if not clean:
            raise ValueError("نام شخص نمی‌تواند خالی باشد.")
        with self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE people SET name = ?, notes = ?, color = ?, updated_at = ? WHERE id = ?",
                (clean, notes.strip(), color, now_local_iso(), int(person_id)),
            )
            if cursor.rowcount == 0:
                raise ValueError("شخص پیدا نشد.")

    def delete_person(self, person_id: int) -> None:
        # Linked journal entries stay intact, with the optional person cleared.
        with self.db.connect() as connection:
            connection.execute("DELETE FROM people WHERE id = ?", (int(person_id),))


    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------
    def tags(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, color, created_at FROM tags ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def add_tag(self, name: str, color: str = "#38BDF8") -> int:
        clean = name.strip()
        if not clean:
            raise ValueError("نام برچسب نمی‌تواند خالی باشد.")
        if len(clean) > 50:
            raise ValueError("نام برچسب نباید بیشتر از ۵۰ نویسه باشد.")
        with self.db.connect() as connection:
            existing = connection.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,)).fetchone()
            if existing:
                return int(existing["id"])
            cursor = connection.execute(
                "INSERT INTO tags(name, color, created_at) VALUES (?, ?, ?)",
                (clean, color, now_local_iso()),
            )
            return int(cursor.lastrowid)

    def update_tag(self, tag_id: int, name: str, color: str = "#38BDF8") -> None:
        clean = name.strip()
        if not clean:
            raise ValueError("نام برچسب نمی‌تواند خالی باشد.")
        with self.db.connect() as connection:
            cursor = connection.execute("UPDATE tags SET name = ?, color = ? WHERE id = ?", (clean, color, int(tag_id)))
            if cursor.rowcount == 0:
                raise ValueError("برچسب پیدا نشد.")

    def delete_tag(self, tag_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM entry_tags WHERE tag_id = ?", (int(tag_id),))
            connection.execute("DELETE FROM tags WHERE id = ?", (int(tag_id),))

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------
    def save_entry(self, data: dict[str, Any], attachment_paths: list[tuple[str, ...]]) -> int:
        title = str(data.get("title", "")).strip()
        event_date = str(data.get("event_date", ""))[:10]
        if not title:
            raise ValueError("عنوان رویداد اجباری است.")
        date.fromisoformat(event_date)
        entry_id = data.get("id")
        now = now_local_iso()
        body = str(data.get("body", ""))
        category_id = data.get("category_id") or None
        person_id = data.get("person_id") or None
        raw_jalali_date = str(data.get("event_jalali_date") or "").strip()
        jalali_date = (
            self._validate_jalali_storage_date(raw_jalali_date, event_date)
            if raw_jalali_date else self._jalali_from_gregorian_iso(event_date)
        )
        is_favorite = 1 if data.get("is_favorite") else 0
        importance = str(data.get("importance") or "normal")
        follow_up_status = str(data.get("follow_up_status") or "none")
        if importance not in {"normal", "important", "critical"}:
            importance = "normal"
        if follow_up_status not in {"none", "pending", "in_progress", "done"}:
            follow_up_status = "none"

        with self.db.connect() as connection:
            if entry_id:
                existing = connection.execute(
                    "SELECT created_at, event_date, event_jalali_date FROM entries WHERE id = ?", (entry_id,)
                ).fetchone()
                if existing is None:
                    raise ValueError("این رکورد دیگر وجود ندارد.")
                if not jalali_date and existing["event_date"] == event_date:
                    jalali_date = existing["event_jalali_date"]
                connection.execute(
                    """UPDATE entries
                       SET title = ?, body = ?, event_date = ?, event_jalali_date = ?,
                           category_id = ?, person_id = ?, is_favorite = ?, importance = ?,
                           follow_up_status = ?, updated_at = ?
                       WHERE id = ?""",
                    (title, body, event_date, jalali_date, category_id, person_id, is_favorite,
                     importance, follow_up_status, now, int(entry_id)),
                )
                saved_id = int(entry_id)
            else:
                cursor = connection.execute(
                    """INSERT INTO entries
                       (title, body, event_date, event_jalali_date, category_id, person_id,
                        is_favorite, importance, follow_up_status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (title, body, event_date, jalali_date, category_id, person_id, is_favorite,
                     importance, follow_up_status, now, now),
                )
                saved_id = int(cursor.lastrowid)

            # Tags are optional and many-to-many. Replacing the set is simple and atomic.
            connection.execute("DELETE FROM entry_tags WHERE entry_id = ?", (saved_id,))
            unique_tag_ids = list(dict.fromkeys(int(value) for value in (data.get("tag_ids") or []) if value))
            for tag_id in unique_tag_ids:
                exists = connection.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone()
                if exists:
                    connection.execute(
                        "INSERT OR IGNORE INTO entry_tags(entry_id, tag_id) VALUES (?, ?)",
                        (saved_id, tag_id),
                    )

            # Preserve per-attachment notes on edit. A two-value tuple (legacy callers)
            # means "keep the existing note"; a three-value tuple explicitly sets it.
            existing_notes = {
                str(row["path"]): str(row["notes"] or "")
                for row in connection.execute(
                    "SELECT path, notes FROM attachments WHERE entry_id = ?", (saved_id,)
                ).fetchall()
            }
            unique_attachments: dict[str, tuple[str, str]] = {}
            for attachment in attachment_paths:
                if len(attachment) < 2:
                    continue
                raw_path, kind = attachment[0], attachment[1]
                note = str(attachment[2]) if len(attachment) >= 3 else existing_notes.get(str(Path(raw_path)), "")
                clean_path = str(Path(raw_path))
                unique_attachments[clean_path] = (str(kind), note)
            for old_path in set(existing_notes) - set(unique_attachments):
                connection.execute(
                    "DELETE FROM attachments WHERE entry_id = ? AND path = ?", (saved_id, old_path)
                )
            for clean_path, (kind, attachment_note) in unique_attachments.items():
                display_name = Path(clean_path).name or clean_path
                connection.execute(
                    """INSERT INTO attachments
                       (entry_id, path, display_name, kind, notes, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(entry_id, path) DO UPDATE SET
                           display_name = excluded.display_name,
                           kind = excluded.kind,
                           notes = excluded.notes""",
                    (saved_id, clean_path, display_name, kind, attachment_note, now),
                )
        return saved_id

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            row = connection.execute(
                """SELECT e.*, c.name AS category_name, c.color AS category_color,
                          p.name AS person_name, p.notes AS person_notes, p.color AS person_color
                   FROM entries e
                   LEFT JOIN categories c ON c.id = e.category_id
                   LEFT JOIN people p ON p.id = e.person_id
                   WHERE e.id = ?""",
                (entry_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["attachments"] = [dict(item) for item in connection.execute(
                "SELECT id, path, display_name, kind, notes FROM attachments WHERE entry_id = ? ORDER BY id",
                (entry_id,),
            ).fetchall()]
            result["tags"] = [dict(item) for item in connection.execute(
                "SELECT t.id, t.name, t.color FROM tags t JOIN entry_tags et ON et.tag_id = t.id "
                "WHERE et.entry_id = ? ORDER BY t.name COLLATE NOCASE", (entry_id,),
            ).fetchall()]
            result["tag_ids"] = [int(item["id"]) for item in result["tags"]]
            result["tag_names"] = "، ".join(item["name"] for item in result["tags"])
            return result

    def list_entries(
        self,
        query: str = "",
        category_id: int | None = None,
        person_id: int | None = None,
        favorites_only: bool = False,
        archived: bool = False,
        limit: int | None = None,
        tag_ids: list[int] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        importance: str | None = None,
        follow_up_status: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """SELECT e.id, e.title, e.body, e.event_date, e.event_jalali_date, e.category_id, e.person_id,
                         e.is_favorite, e.is_archived, e.importance, e.follow_up_status, e.created_at, e.updated_at,
                         c.name AS category_name, c.color AS category_color,
                         p.name AS person_name, p.color AS person_color,
                         (SELECT COUNT(*) FROM attachments a WHERE a.entry_id = e.id) AS attachment_count,
                         COALESCE((SELECT GROUP_CONCAT(t.name, '، ') FROM entry_tags et JOIN tags t ON t.id = et.tag_id
                                   WHERE et.entry_id = e.id), '') AS tag_names,
                         (SELECT COUNT(*) FROM entry_tags et WHERE et.entry_id = e.id) AS tag_count
                  FROM entries e
                  LEFT JOIN categories c ON c.id = e.category_id
                  LEFT JOIN people p ON p.id = e.person_id
                  WHERE e.is_archived = ?"""
        params: list[Any] = [1 if archived else 0]
        if query.strip():
            needle = f"%{query.strip()}%"
            sql += """ AND (
                e.title LIKE ? OR e.body LIKE ? OR COALESCE(c.name, '') LIKE ?
                OR COALESCE(p.name, '') LIKE ?
                OR EXISTS (SELECT 1 FROM attachments a WHERE a.entry_id=e.id AND (a.display_name LIKE ? OR a.path LIKE ?))
                OR EXISTS (SELECT 1 FROM entry_tags et JOIN tags t ON t.id=et.tag_id WHERE et.entry_id=e.id AND t.name LIKE ?)
            )"""
            params.extend([needle, needle, needle, needle, needle, needle, needle])
        if category_id is not None:
            sql += " AND e.category_id = ?"
            params.append(category_id)
        if person_id is not None:
            sql += " AND e.person_id = ?"
            params.append(person_id)
        selected_tags = list(dict.fromkeys(int(tag_id) for tag_id in (tag_ids or [])))
        if selected_tags:
            placeholders = ",".join("?" for _ in selected_tags)
            sql += f" AND EXISTS (SELECT 1 FROM entry_tags et WHERE et.entry_id=e.id AND et.tag_id IN ({placeholders}))"
            params.extend(selected_tags)
        if date_from:
            sql += " AND e.event_date >= ?"
            params.append(str(date_from)[:10])
        if date_to:
            sql += " AND e.event_date <= ?"
            params.append(str(date_to)[:10])
        if favorites_only:
            sql += " AND e.is_favorite = 1"
        if importance in {"normal", "important", "critical"}:
            sql += " AND e.importance = ?"
            params.append(importance)
        if follow_up_status in {"none", "pending", "in_progress", "done"}:
            sql += " AND e.follow_up_status = ?"
            params.append(follow_up_status)
        sql += " ORDER BY e.event_date DESC, e.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def memories_on_this_day(self, jalali_today: str) -> list[dict[str, Any]]:
        """Return entries from previous Jalali years with today's month/day.

        ``jalali_today`` is a full Jalali date in YYYY-MM-DD form. The query
        intentionally includes archived entries so a user's old memories are
        not hidden merely because they were archived.
        """
        pieces = str(jalali_today).strip().replace('.', '-').replace('/', '-').split('-')
        if len(pieces) != 3 or not all(part.isdigit() for part in pieces):
            raise ValueError("تاریخ شمسی برای مرور خاطرات معتبر نیست.")
        year, month, day = (int(part) for part in pieces)
        if year < 1 or not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError("تاریخ شمسی برای مرور خاطرات معتبر نیست.")
        month_day = f"{month:02d}-{day:02d}"
        sql = """SELECT e.id, e.title, e.body, e.event_date, e.event_jalali_date,
                         e.category_id, e.person_id, e.is_favorite, e.is_archived,
                         e.importance, e.follow_up_status, e.created_at, e.updated_at,
                         c.name AS category_name, c.color AS category_color,
                         p.name AS person_name, p.color AS person_color,
                         (SELECT COUNT(*) FROM attachments a WHERE a.entry_id=e.id) AS attachment_count,
                         COALESCE((SELECT GROUP_CONCAT(t.name, '، ') FROM entry_tags et
                                   JOIN tags t ON t.id=et.tag_id WHERE et.entry_id=e.id), '') AS tag_names,
                         (SELECT COUNT(*) FROM entry_tags et WHERE et.entry_id=e.id) AS tag_count
                  FROM entries e
                  LEFT JOIN categories c ON c.id=e.category_id
                  LEFT JOIN people p ON p.id=e.person_id
                  WHERE e.event_jalali_date IS NOT NULL
                    AND length(e.event_jalali_date) >= 10
                    AND substr(e.event_jalali_date, 6, 5)=?
                    AND CAST(substr(e.event_jalali_date, 1, 4) AS INTEGER) < ?
                  ORDER BY CAST(substr(e.event_jalali_date, 1, 4) AS INTEGER) DESC,
                           e.event_date DESC, e.id DESC"""
        with self.db.connect() as connection:
            rows = connection.execute(sql, (month_day, year)).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self.db.connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN is_favorite = 1 THEN 1 ELSE 0 END) AS favorites,
                          SUM(CASE WHEN event_date = ? THEN 1 ELSE 0 END) AS today,
                          SUM(CASE WHEN is_archived = 1 THEN 1 ELSE 0 END) AS archived
                   FROM entries""", (date.today().isoformat(),)
            ).fetchone()
            attachments = connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
            people_count = connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]
            categories_count = connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
            follow_rows = connection.execute(
                "SELECT follow_up_status, COUNT(*) AS amount FROM entries "
                "WHERE is_archived = 0 GROUP BY follow_up_status"
            ).fetchall()
            importance_rows = connection.execute(
                "SELECT importance, COUNT(*) AS amount FROM entries "
                "WHERE is_archived = 0 GROUP BY importance"
            ).fetchall()
            follow_counts = {str(row["follow_up_status"] or "none"): int(row["amount"] or 0) for row in follow_rows}
            importance_counts = {str(row["importance"] or "normal"): int(row["amount"] or 0) for row in importance_rows}
            return {
                "total": int(totals["total"] or 0),
                "favorites": int(totals["favorites"] or 0),
                "today": int(totals["today"] or 0),
                "archived": int(totals["archived"] or 0),
                "attachments": int(attachments or 0),
                "people": int(people_count or 0),
                "categories": int(categories_count or 0),
                "follow_up_total": sum(follow_counts.values()),
                "follow_up_none": follow_counts.get("none", 0),
                "follow_up_pending": follow_counts.get("pending", 0),
                "follow_up_in_progress": follow_counts.get("in_progress", 0),
                "follow_up_done": follow_counts.get("done", 0),
                "importance_total": sum(importance_counts.values()),
                "importance_normal": importance_counts.get("normal", 0),
                "importance_important": importance_counts.get("important", 0),
                "importance_critical": importance_counts.get("critical", 0),
            }

    def toggle_favorite(self, entry_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE entries SET is_favorite = CASE is_favorite WHEN 1 THEN 0 ELSE 1 END, updated_at = ? WHERE id = ?",
                (now_local_iso(), entry_id),
            )

    def delete_entry(self, entry_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM entries WHERE id = ?", (entry_id,))

    def archive_entry(self, entry_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE entries SET is_archived = 1, updated_at = ? WHERE id = ?",
                (now_local_iso(), entry_id),
            )

    def unarchive_entry(self, entry_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE entries SET is_archived = 0, updated_at = ? WHERE id = ?",
                (now_local_iso(), entry_id),
            )
