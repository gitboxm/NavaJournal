from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path

import nava_update_worker

_NEW_WORKER_PATH = Path(__file__).resolve().parents[1] / "nava_journal" / "update_worker.py"
_NEW_WORKER_SPEC = importlib.util.spec_from_file_location("nava_current_update_worker", _NEW_WORKER_PATH)
_NEW_WORKER = importlib.util.module_from_spec(_NEW_WORKER_SPEC)
assert _NEW_WORKER_SPEC and _NEW_WORKER_SPEC.loader
_NEW_WORKER_SPEC.loader.exec_module(_NEW_WORKER)


class UpdateWorkerTests(unittest.TestCase):
    def test_applies_only_listed_file_and_restarts(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "app"
            data = base / "data"
            stage = data / "staging" / "one"
            backup = data / "backups" / "one"
            (root / "nava_journal").mkdir(parents=True)
            stage.mkdir(parents=True)
            (root / "main.py").write_text("# main unchanged\n", encoding="utf-8")
            (root / "nava_journal" / "pages.py").write_text("# old\n", encoding="utf-8")
            (root / "nava_journal" / "repository.py").write_text("# must not change\n", encoding="utf-8")
            (stage / "nava_journal").mkdir()
            (stage / "nava_journal" / "pages.py").write_text("# updated\n", encoding="utf-8")
            status_path = data / "updates" / "last_update.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({"state": "ready_to_restart", "timeline": []}), encoding="utf-8")
            marker = base / "restarted.txt"
            pending_path = data / "pending.json"
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            pending = {
                "install_root": str(root),
                "data_dir": str(data),
                "stage_dir": str(stage),
                "backup_dir": str(backup),
                "status_path": str(status_path),
                "files": ["nava_journal/pages.py"],
                "parent_pid": 9_999_999,
                "python_executable": sys.executable,
                "restart_args": ["-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('started')"],
                "base_version": "0.3.0",
                "target_version": "0.3.1",
                "release_notes": ["test patch"],
            }
            pending_path.write_text(json.dumps(pending), encoding="utf-8")

            result = nava_update_worker.run(pending_path)
            self.assertEqual(result, 0)
            self.assertEqual((root / "nava_journal" / "pages.py").read_text(encoding="utf-8"), "# updated\n")
            self.assertEqual((root / "nava_journal" / "repository.py").read_text(encoding="utf-8"), "# must not change\n")
            self.assertTrue((backup / "nava_journal" / "pages.py").is_file())
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "restarted")
            self.assertTrue(any(item.get("state") == "file_replaced" for item in status["timeline"]))
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "the restart command should have been launched")

    def test_rollback_restores_previous_file_and_removes_new_optional_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "app"
            data = base / "data"
            stage = data / "staging" / "rollback"
            backup = data / "backups" / "rollback"
            package = root / "nava_journal"
            package.mkdir(parents=True)
            (package / "pages.py").write_text("# updated hook\n", encoding="utf-8")
            (package / "recent_row_layout.py").write_text("# newly installed module\n", encoding="utf-8")
            stage_package = stage / "nava_journal"
            stage_package.mkdir(parents=True)
            (stage_package / "pages.py").write_text("# previous hook\n", encoding="utf-8")
            status_path = data / "updates" / "last_update.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({"state": "preparing_rollback", "operation": "rollback", "timeline": []}), encoding="utf-8")
            marker = base / "restarted.txt"
            pending_path = data / "pending_rollback.json"
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            pending = {
                "app_id": "nava-journal", "operation": "rollback",
                "install_root": str(root), "data_dir": str(data),
                "stage_dir": str(stage), "backup_dir": str(backup),
                "status_path": str(status_path),
                "files": ["nava_journal/pages.py", "nava_journal/recent_row_layout.py"],
                "parent_pid": 9_999_999,
                "python_executable": sys.executable,
                "restart_args": ["-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('started')"],
                "base_version": "0.4.4", "target_version": "0.4.3.1",
                "restore_database": False,
            }
            pending_path.write_text(json.dumps(pending), encoding="utf-8")

            result = _NEW_WORKER.run(pending_path)
            self.assertEqual(result, 0)
            self.assertEqual((package / "pages.py").read_text(encoding="utf-8"), "# previous hook\n")
            self.assertFalse((package / "recent_row_layout.py").exists())
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "rolled_back")
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "the previous version should be relaunched")


if __name__ == "__main__":
    unittest.main()
