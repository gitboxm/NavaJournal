from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from nava_journal.auto_backup import BACKUP_FOLDER_NAME, create_close_backup
from nava_journal.db import Database
from nava_journal.repository import JournalRepository


class AutomaticCloseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.db = Database(self.base / "live" / "journal.sqlite3")
        self.repo = JournalRepository(self.db)
        self.entry_id = self.repo.save_entry(
            {"title": "مورد آزمایشی", "body": "این اطلاعات باید باقی بماند", "event_date": "2026-10-29"}, []
        )
        self.install_root = self.base / "application"
        self.install_root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 10, 29, 8, 24, 31, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_close_backup_is_timestamped_jalali_and_does_not_change_live_database(self):
        source_path = self.db.path
        source_before = self._sha256(source_path)
        live_count_before = len(self.repo.list_entries(archived=None))
        with patch("nava_journal.auto_backup._jalali_date_label", return_value="1405.08.07"):
            output, used_fallback = create_close_backup(self.db, root=self.install_root, now=self.now)

        jalali = "1405.08.07"
        self.assertEqual(output.parent, self.install_root / BACKUP_FOLDER_NAME)
        self.assertIn(jalali, output.name)
        self.assertIn("08-24-31", output.name)
        self.assertFalse(used_fallback)
        self.assertTrue(output.is_file())
        self.assertEqual(self.db.path, source_path)
        self.assertEqual(self._sha256(source_path), source_before)
        self.assertEqual(len(self.repo.list_entries(archived=None)), live_count_before)

        with sqlite3.connect(output) as snapshot:
            self.assertEqual(snapshot.execute("PRAGMA quick_check").fetchone()[0], "ok")
            row = snapshot.execute("SELECT title, body FROM entries WHERE id = ?", (self.entry_id,)).fetchone()
        self.assertEqual(row, ("مورد آزمایشی", "این اطلاعات باید باقی بماند"))

    def test_repeated_backup_same_second_never_overwrites_previous_snapshot(self):
        with patch("nava_journal.auto_backup._jalali_date_label", return_value="1405.08.07"):
            first, _ = create_close_backup(self.db, root=self.install_root, now=self.now)
            original_bytes = first.read_bytes()
            second, _ = create_close_backup(self.db, root=self.install_root, now=self.now)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(first.read_bytes(), original_bytes)
        self.assertTrue(second.exists())


if __name__ == "__main__":
    unittest.main()
