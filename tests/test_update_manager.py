from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from nava_journal.update_manager import UpdateError, UpdateManager


class UpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "app"
        self.data = Path(self.temp.name) / "data"
        self.root.mkdir()
        (self.root / "main.py").write_text("# old", encoding="utf-8")
        (self.root / "nava_journal").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_zip(self, path: Path, relative: str = "nava_journal/pages.py", base: str = "0.3.0") -> Path:
        content = b"# changed UI\n"
        manifest = {
            "format_version": 1,
            "app_id": "nava-journal",
            "base_version": base,
            "version": "0.3.1",
            "release_notes": ["Test patch"],
            "files": [{"path": relative, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
            archive.writestr(f"files/{relative}", content)
        return path

    def test_valid_differential_patch_is_inspected(self):
        patch = self.make_zip(Path(self.temp.name) / "patch.zip")
        manager = UpdateManager(self.root, self.data, "0.3.0")
        result = manager.inspect_update(patch)
        self.assertEqual(result["version"], "0.3.1")
        self.assertEqual([item["path"] for item in result["files"]], ["nava_journal/pages.py"])

    def test_rejects_path_traversal(self):
        patch = self.make_zip(Path(self.temp.name) / "bad.zip", "nava_journal/../main.py")
        manager = UpdateManager(self.root, self.data, "0.3.0")
        with self.assertRaises(UpdateError):
            manager.inspect_update(patch)

    def test_rejects_wrong_base_version(self):
        patch = self.make_zip(Path(self.temp.name) / "wrong_base.zip", base="0.2.1")
        manager = UpdateManager(self.root, self.data, "0.3.0")
        with self.assertRaises(UpdateError):
            manager.inspect_update(patch)

    def test_prepare_update_stages_only_listed_files_and_backups_database(self):
        patch = self.make_zip(Path(self.temp.name) / "prepare.zip")
        manager = UpdateManager(self.root, self.data, "0.3.0")

        class FakeDatabase:
            def backup_to(self, destination):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"sqlite backup test")
                return destination

        pending_path, manifest = manager.prepare_update(patch, FakeDatabase())
        import json
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        staged = Path(pending["stage_dir"]) / "nava_journal" / "pages.py"
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), b"# changed UI\n")
        self.assertTrue(Path(pending["database_backup"]).is_file())
        self.assertEqual(pending["files"], ["nava_journal/pages.py"])
        status = manager.read_last_status()
        self.assertTrue(status["timeline"])
        self.assertEqual(manifest["version"], "0.3.1")

    def test_selective_groups_and_mandatory_files(self):
        patch = Path(self.temp.name) / "grouped.zip"
        records = {
            "nava_journal/pages.py": b"# base hook\n",
            "nava_journal/version.py": b'APP_VERSION = "0.3.1"\n',
            "nava_journal/dashboard_header.py": b"# dashboard only\n",
            "nava_journal/recent_row.py": b"# recent row only\n",
        }
        manifest = {
            "format_version": 1,
            "app_id": "nava-journal",
            "base_version": "0.3.0",
            "version": "0.3.1",
            "release_notes": ["Test selectable changes"],
            "always_apply_files": ["nava_journal/pages.py", "nava_journal/version.py"],
            "change_groups": [
                {"id": "dashboard", "title": "Dashboard", "description": "Dashboard header only", "files": ["nava_journal/dashboard_header.py"]},
                {"id": "recent", "title": "Recent row", "description": "First row only", "files": ["nava_journal/recent_row.py"]},
            ],
            "files": [
                {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                for name, content in records.items()
            ],
        }
        with zipfile.ZipFile(patch, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
            for name, content in records.items():
                archive.writestr(f"files/{name}", content)

        manager = UpdateManager(self.root, self.data, "0.3.0")
        inspected = manager.inspect_update(patch)
        selected_records, selected_groups = manager.selected_file_records(inspected, {"dashboard"})
        self.assertEqual({item["path"] for item in selected_records}, {
            "nava_journal/pages.py", "nava_journal/version.py", "nava_journal/dashboard_header.py"
        })
        self.assertEqual([item["id"] for item in selected_groups], ["dashboard"])
        self.assertNotIn("nava_journal/recent_row.py", {item["path"] for item in selected_records})

    def test_rollback_stages_previous_files_and_keeps_current_database_by_default(self):
        import json
        from datetime import datetime

        manager = UpdateManager(self.root, self.data, "0.3.1")
        update_dir = self.data / "updates"
        backup_dir = update_dir / "file_backups" / "previous_update"
        previous_file = backup_dir / "nava_journal" / "pages.py"
        previous_file.parent.mkdir(parents=True, exist_ok=True)
        previous_file.write_text("# previous version\n", encoding="utf-8")
        current_file = self.root / "nava_journal" / "pages.py"
        current_file.write_text("# current version\n", encoding="utf-8")
        update_dir.mkdir(parents=True, exist_ok=True)
        status = {
            "app_id": "nava-journal",
            "operation": "update",
            "base_version": "0.3.0",
            "target_version": "0.3.1",
            "state": "completed",
            "files": ["nava_journal/pages.py"],
            "backup_dir": str(backup_dir),
            "timeline": [],
        }
        (update_dir / "last_update.json").write_text(json.dumps(status), encoding="utf-8")

        class FakeDatabase:
            path = Path(self.data / "journal.sqlite3")
            def backup_to(self, destination):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"current sqlite snapshot")
                return destination

        allowed, _, _ = manager.rollback_capability()
        self.assertTrue(allowed)
        pending_path, rollback_manifest = manager.prepare_rollback(FakeDatabase(), restore_database=False)
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        self.assertEqual(pending["operation"], "rollback")
        self.assertFalse(pending["restore_database"])
        staged_previous = Path(pending["stage_dir"]) / "nava_journal" / "pages.py"
        self.assertEqual(staged_previous.read_text(encoding="utf-8"), "# previous version\n")
        self.assertEqual(rollback_manifest["version"], "0.3.0")

    def test_rejects_hash_mismatch(self):
        original = self.make_zip(Path(self.temp.name) / "source.zip")
        patch = Path(self.temp.name) / "hash.zip"
        with zipfile.ZipFile(original, "r") as source, zipfile.ZipFile(patch, "w", zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                content = b"tampered" if name == "files/nava_journal/pages.py" else source.read(name)
                target.writestr(name, content)
        manager = UpdateManager(self.root, self.data, "0.3.0")
        with self.assertRaises(UpdateError):
            manager.inspect_update(patch)


if __name__ == "__main__":
    unittest.main()
