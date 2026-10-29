import sqlite3
import tempfile
import unittest
from pathlib import Path

from nava_journal.db import Database
from nava_journal.repository import JournalRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        self.repo = JournalRepository(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_and_seed_categories(self):
        self.assertEqual(self.db.schema_version(), 5)
        self.assertEqual(self.db.quick_check(), "ok")
        self.assertGreaterEqual(len(self.repo.categories()), 5)

    def test_create_search_favorite_archive_and_delete(self):
        category = self.repo.categories()[0]
        entry_id = self.repo.save_entry({
            "title": "آزمایش ژورنال",
            "body": "متن آزمایشی",
            "event_date": "2026-10-29",
            "category_id": category["id"],
            "is_favorite": False,
        }, [])
        entry = self.repo.get_entry(entry_id)
        self.assertEqual(entry["title"], "آزمایش ژورنال")
        self.assertEqual(len(self.repo.list_entries(query="آزمایش")), 1)
        self.repo.toggle_favorite(entry_id)
        self.assertEqual(self.repo.list_entries(favorites_only=True)[0]["id"], entry_id)
        self.repo.archive_entry(entry_id)
        self.assertEqual(len(self.repo.list_entries(archived=False)), 0)
        self.assertEqual(len(self.repo.list_entries(archived=True)), 1)
        self.repo.unarchive_entry(entry_id)
        self.repo.delete_entry(entry_id)
        self.assertIsNone(self.repo.get_entry(entry_id))

    def test_v3_database_migrates_to_v5_and_preserves_existing_entry(self):
        legacy_path = Path(self.temp.name) / "legacy_v3.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript("""
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    event_date TEXT NOT NULL,
                    event_jalali_date TEXT,
                    category_id INTEGER,
                    person_id INTEGER,
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'file',
                    created_at TEXT NOT NULL,
                    UNIQUE(entry_id, path)
                );
                INSERT INTO entries(title, body, event_date, event_jalali_date, created_at, updated_at)
                  VALUES ('Existing row', 'Keep this', '2026-10-29', '1405-08-07', 'created', 'updated');
                PRAGMA user_version = 3;
            """)
        upgraded = Database(legacy_path)
        self.assertEqual(upgraded.schema_version(), 5)
        with upgraded.connect() as connection:
            row = connection.execute(
                "SELECT title, body, event_jalali_date, importance, follow_up_status FROM entries WHERE id = 1"
            ).fetchone()
        self.assertEqual(row["title"], "Existing row")
        self.assertEqual(row["body"], "Keep this")
        self.assertEqual(row["event_jalali_date"], "1405-08-07")
        self.assertEqual(row["importance"], "normal")
        self.assertEqual(row["follow_up_status"], "none")

    def test_importance_and_follow_up_are_optional_and_searchable(self):
        normal_id = self.repo.save_entry({
            "title": "یادداشت معمولی", "event_date": "2026-10-29"
        }, [])
        flagged_id = self.repo.save_entry({
            "title": "پیگیری مهم", "event_date": "2026-10-29",
            "importance": "critical", "follow_up_status": "pending",
        }, [])
        normal = self.repo.get_entry(normal_id)
        flagged = self.repo.get_entry(flagged_id)
        self.assertEqual(normal["importance"], "normal")
        self.assertEqual(normal["follow_up_status"], "none")
        self.assertEqual(flagged["importance"], "critical")
        self.assertEqual(flagged["follow_up_status"], "pending")
        self.assertEqual([row["id"] for row in self.repo.list_entries(importance="critical")], [flagged_id])
        self.assertEqual([row["id"] for row in self.repo.list_entries(follow_up_status="pending")], [flagged_id])
        self.repo.save_entry({
            "id": flagged_id, "title": "پیگیری انجام شد", "event_date": "2026-10-29",
            "importance": "important", "follow_up_status": "done",
        }, [])
        updated = self.repo.get_entry(flagged_id)
        self.assertEqual(updated["importance"], "important")
        self.assertEqual(updated["follow_up_status"], "done")

    def test_dashboard_stats_include_follow_up_and_importance_breakdowns(self):
        pending_id = self.repo.save_entry({
            "title": "پیگیری باز", "event_date": "2026-10-29",
            "follow_up_status": "pending", "importance": "important",
        }, [])
        done_id = self.repo.save_entry({
            "title": "پیگیری تمام‌شده", "event_date": "2026-10-29",
            "follow_up_status": "done", "importance": "critical",
        }, [])
        normal_id = self.repo.save_entry({
            "title": "رویداد معمولی", "event_date": "2026-10-29",
            "follow_up_status": "none", "importance": "normal",
        }, [])
        self.repo.archive_entry(normal_id)
        stats = self.repo.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["archived"], 1)
        self.assertEqual(stats["follow_up_total"], 2)
        self.assertEqual(stats["follow_up_pending"], 1)
        self.assertEqual(stats["follow_up_done"], 1)
        self.assertEqual(stats["follow_up_none"], 0)
        self.assertEqual(stats["importance_total"], 2)
        self.assertEqual(stats["importance_important"], 1)
        self.assertEqual(stats["importance_critical"], 1)
        self.assertEqual(stats["importance_normal"], 0)

    def test_created_at_is_preserved_when_editing(self):
        entry_id = self.repo.save_entry({"title": "Original", "event_date": "2026-10-29"}, [])
        original = self.repo.get_entry(entry_id)["created_at"]
        self.repo.save_entry({"id": entry_id, "title": "Edited", "event_date": "2026-10-30"}, [])
        edited = self.repo.get_entry(entry_id)
        self.assertEqual(edited["created_at"], original)
        self.assertNotEqual(edited["updated_at"], "")



    def test_v1_database_migrates_to_v5_without_losing_entries(self):
        legacy_path = Path(self.temp.name) / "legacy_v1.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript("""
                CREATE TABLE categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    color TEXT NOT NULL DEFAULT '#8B7CF6',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    event_date TEXT NOT NULL,
                    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'file',
                    created_at TEXT NOT NULL,
                    UNIQUE(entry_id, path)
                );
                CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL DEFAULT '#38BDF8', created_at TEXT NOT NULL);
                CREATE TABLE entry_tags (entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE, tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(entry_id, tag_id));
                INSERT INTO categories(name, color, created_at) VALUES ('Legacy category', '#8B7CF6', '2026-10-01T10:00:00+00:00');
                INSERT INTO entries(title, body, event_date, category_id, created_at, updated_at)
                    VALUES ('Legacy title', 'Legacy body', '2026-10-29', 1, '2026-10-01T10:00:00+00:00', '2026-10-01T10:00:00+00:00');
                PRAGMA user_version = 1;
            """)
        upgraded = Database(legacy_path)
        upgraded_repo = JournalRepository(upgraded)
        entry = upgraded_repo.get_entry(1)
        self.assertEqual(upgraded.schema_version(), 5)
        self.assertEqual(entry["title"], "Legacy title")
        self.assertEqual(entry["category_name"], "Legacy category")
        self.assertIsNone(entry["person_id"])
        self.assertEqual(upgraded.quick_check(), "ok")

    def test_people_can_be_added_edited_and_linked_optionally(self):
        person_id = self.repo.add_person("علی رضایی", "همکار پروژه", "#38BDF8")
        entry_id = self.repo.save_entry({
            "title": "جلسه با علی",
            "event_date": "2026-10-29",
            "person_id": person_id,
        }, [])
        entry = self.repo.get_entry(entry_id)
        self.assertEqual(entry["person_id"], person_id)
        self.assertEqual(entry["person_name"], "علی رضایی")
        self.assertEqual(len(self.repo.list_entries(query="علی")), 1)

        self.repo.update_person(person_id, "علی رضایی", "اطلاعات تکمیل شد", "#00AACC")
        self.assertEqual(self.repo.get_entry(entry_id)["person_name"], "علی رضایی")
        self.repo.delete_person(person_id)
        entry_after_delete = self.repo.get_entry(entry_id)
        self.assertIsNone(entry_after_delete["person_id"])
        self.assertEqual(entry_after_delete["title"], "جلسه با علی")

    def test_full_jalali_year_is_stored_separately_from_compact_display(self):
        entry_id = self.repo.save_entry({
            "title": "تاریخ شمسی کامل",
            "event_date": "2026-10-29",
            "event_jalali_date": "1405-08-07",
        }, [])
        entry = self.repo.get_entry(entry_id)
        self.assertEqual(entry["event_date"], "2026-10-29")
        self.assertEqual(entry["event_jalali_date"], "1405-08-07")

    def test_category_can_be_renamed_without_losing_entry(self):
        category_id = self.repo.add_category("پیگیری", "#9988EE")
        entry_id = self.repo.save_entry({
            "title": "آیتم دسته‌بندی",
            "event_date": "2026-10-29",
            "category_id": category_id,
        }, [])
        self.repo.update_category(category_id, "پیگیری مهم", "#7766DD")
        self.assertEqual(self.repo.get_entry(entry_id)["category_name"], "پیگیری مهم")
        self.repo.delete_category(category_id)
        updated = self.repo.get_entry(entry_id)
        self.assertIsNone(updated["category_id"])
        self.assertEqual(updated["title"], "آیتم دسته‌بندی")

    def test_multiple_tags_roundtrip_and_optional_selection(self):
        tag_one = self.repo.add_tag("پروژه")
        tag_two = self.repo.add_tag("مهم", "#F59E0B")
        entry_id = self.repo.save_entry({
            "title": "رویداد دارای برچسب",
            "event_date": "2026-10-29",
            "tag_ids": [tag_one, tag_two],
        }, [])
        entry = self.repo.get_entry(entry_id)
        self.assertEqual(set(entry["tag_ids"]), {tag_one, tag_two})
        self.assertIn("پروژه", entry["tag_names"])
        self.assertEqual(len(self.repo.list_entries(tag_ids=[tag_one])), 1)
        self.assertEqual(len(self.repo.list_entries(query="مهم")), 1)

        # Selecting no tag is supported and doesn't make tags mandatory.
        other_id = self.repo.save_entry({"title": "بدون برچسب", "event_date": "2026-10-30"}, [])
        self.assertEqual(self.repo.get_entry(other_id)["tag_ids"], [])
        self.assertEqual(len(self.repo.list_entries(tag_ids=[tag_two])), 1)

    def test_tag_rename_and_delete_preserve_entries(self):
        tag_id = self.repo.add_tag("اولیه")
        entry_id = self.repo.save_entry({"title": "نمونه", "event_date": "2026-10-29", "tag_ids": [tag_id]}, [])
        self.repo.update_tag(tag_id, "تغییر یافته", "#AABBCC")
        self.assertEqual(self.repo.get_entry(entry_id)["tag_names"], "تغییر یافته")
        self.repo.delete_tag(tag_id)
        entry = self.repo.get_entry(entry_id)
        self.assertEqual(entry["title"], "نمونه")
        self.assertEqual(entry["tag_ids"], [])

    def test_advanced_search_date_and_tag_filters(self):
        first_tag = self.repo.add_tag("آرشیو")
        old_id = self.repo.save_entry({"title": "قدیمی", "event_date": "2026-10-01", "tag_ids": [first_tag]}, [])
        new_id = self.repo.save_entry({"title": "جدید", "event_date": "2026-10-29", "tag_ids": [first_tag]}, [])
        only_later = self.repo.list_entries(tag_ids=[first_tag], date_from="2026-10-15", date_to="2026-10-31")
        self.assertEqual([row["id"] for row in only_later], [new_id])
        self.assertNotEqual(old_id, new_id)

    def test_attachment_roundtrip_and_backup(self):
        fake_path = str(Path(self.temp.name) / "document.pdf")
        entry_id = self.repo.save_entry(
            {"title": "With attachment", "event_date": "2026-10-28"},
            [(fake_path, "file")],
        )
        entry = self.repo.get_entry(entry_id)
        self.assertEqual(entry["attachments"][0]["path"], fake_path)
        self.assertEqual(entry["attachments"][0]["kind"], "file")
        backup_path = Path(self.temp.name) / "backup.sqlite3"
        self.db.backup_to(backup_path)
        self.assertTrue(backup_path.exists())
        backup = Database(backup_path)
        self.assertEqual(backup.quick_check(), "ok")
        self.assertEqual(JournalRepository(backup).get_entry(entry_id)["title"], "With attachment")

    def test_v4_migration_adds_attachment_notes_without_losing_attachment(self):
        legacy_path = Path(self.temp.name) / "legacy_v4.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript("""
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    event_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'file',
                    created_at TEXT NOT NULL,
                    UNIQUE(entry_id, path)
                );
                INSERT INTO entries(title, event_date, created_at, updated_at)
                    VALUES ('Keep attachment', '2026-10-29', 'created', 'updated');
                INSERT INTO attachments(entry_id, path, display_name, kind, created_at)
                    VALUES (1, '/tmp/keep.txt', 'keep.txt', 'file', 'created');
                PRAGMA user_version = 4;
            """)
        upgraded = Database(legacy_path)
        with upgraded.connect() as connection:
            row = connection.execute("SELECT path, notes FROM attachments WHERE id = 1").fetchone()
        self.assertEqual(upgraded.schema_version(), 5)
        self.assertEqual(row["path"], "/tmp/keep.txt")
        self.assertEqual(row["notes"], "")
        self.assertEqual(upgraded.quick_check(), "ok")

    def test_attachment_notes_roundtrip_and_preserved_when_using_legacy_tuple(self):
        fake_path = str(Path(self.temp.name) / "noted-document.pdf")
        entry_id = self.repo.save_entry(
            {"title": "Attachment note", "event_date": "2026-10-29"},
            [(fake_path, "file", "برای پیگیری قرارداد")],
        )
        self.assertEqual(self.repo.get_entry(entry_id)["attachments"][0]["notes"], "برای پیگیری قرارداد")
        self.repo.save_entry(
            {"id": entry_id, "title": "Edited title", "event_date": "2026-10-29"},
            [(fake_path, "file")],
        )
        self.assertEqual(self.repo.get_entry(entry_id)["attachments"][0]["notes"], "برای پیگیری قرارداد")
        self.repo.save_entry(
            {"id": entry_id, "title": "Edited title", "event_date": "2026-10-29"},
            [(fake_path, "file", "")],
        )
        self.assertEqual(self.repo.get_entry(entry_id)["attachments"][0]["notes"], "")

    def test_move_database_to_new_location_and_switch_removes_original(self):
        entry_id = self.repo.save_entry({"title": "Keep me", "event_date": "2026-10-29"}, [])
        original = self.db.path
        destination = Path(self.temp.name) / "moved" / "journal.sqlite3"
        self.db.move_to_and_switch(destination)
        self.assertEqual(self.db.path, destination.resolve())
        self.assertFalse(original.exists(), "successful move should remove the database file from the old path")
        self.assertTrue(destination.exists())
        self.assertEqual(self.repo.get_entry(entry_id)["title"], "Keep me")
        self.assertEqual(self.db.quick_check(), "ok")

    def test_move_database_replaces_existing_destination_but_preserves_old_destination(self):
        self.repo.save_entry({"title": "Move source", "event_date": "2026-10-29"}, [])
        destination = Path(self.temp.name) / "target" / "journal.sqlite3"
        destination.parent.mkdir(parents=True)
        destination_db = Database(destination)
        destination_repo = JournalRepository(destination_db)
        destination_repo.save_entry({"title": "Old destination", "event_date": "2026-10-28"}, [])
        source_path = self.db.path

        moved = self.db.move_to_and_switch(destination, overwrite=True)
        self.assertEqual(moved, destination.resolve())
        self.assertFalse(source_path.exists())
        titles = [row["title"] for row in self.repo.list_entries()]
        self.assertEqual(titles, ["Move source"])
        preserved = list(destination.parent.glob("journal.replaced_*.sqlite3"))
        self.assertEqual(len(preserved), 1)
        with sqlite3.connect(preserved[0]) as connection:
            self.assertEqual(connection.execute("SELECT title FROM entries").fetchone()[0], "Old destination")


if __name__ == "__main__":
    unittest.main()
