from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "build_update_patch.py"
SPEC = importlib.util.spec_from_file_location("build_update_patch", SCRIPT)
BUILD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(BUILD)


class PatchBuilderTests(unittest.TestCase):
    def test_patch_contains_only_new_or_changed_allowed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "base"
            target = Path(temporary) / "target"
            output = Path(temporary) / "update.zip"
            (base / "nava_journal").mkdir(parents=True)
            (target / "nava_journal").mkdir(parents=True)
            (base / "main.py").write_text("# unchanged\n", encoding="utf-8")
            (target / "main.py").write_text("# unchanged\n", encoding="utf-8")
            (base / "nava_journal" / "pages.py").write_text("# old\n", encoding="utf-8")
            (target / "nava_journal" / "pages.py").write_text("# new\n", encoding="utf-8")
            (base / "nava_journal" / "repository.py").write_text("# stable\n", encoding="utf-8")
            (target / "nava_journal" / "repository.py").write_text("# stable\n", encoding="utf-8")
            (target / "nava_journal" / "version.py").write_text('APP_VERSION = "0.3.1"\n', encoding="utf-8")
            (target / "requirements.txt").write_text("different deps\n", encoding="utf-8")

            count = BUILD.make_patch(base, target, output, "0.3.0", "0.3.1", ["Only changed files"])
            self.assertEqual(count, 2)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertEqual(names, {
                    "manifest.json",
                    "files/nava_journal/pages.py",
                    "files/nava_journal/version.py",
                })
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["base_version"], "0.3.0")
                self.assertEqual(manifest["version"], "0.3.1")
                self.assertEqual({row["path"] for row in manifest["files"]}, {
                    "nava_journal/pages.py", "nava_journal/version.py"
                })

    def test_selective_patch_records_groups_and_mandatory_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "base"
            target = Path(temporary) / "target"
            output = Path(temporary) / "selective.zip"
            (base / "nava_journal").mkdir(parents=True)
            (target / "nava_journal").mkdir(parents=True)
            names = {
                "nava_journal/pages.py": b"# core hook\n",
                "nava_journal/version.py": b'APP_VERSION = "0.4.4"\n',
                "nava_journal/dashboard_header_layout.py": b"# optional dashboard\n",
                "nava_journal/recent_card_first_row_layout.py": b"# optional recent row\n",
            }
            for name in names:
                old = base / name
                old.parent.mkdir(parents=True, exist_ok=True)
                old.write_bytes(b"# old\n")
                current = target / name
                current.parent.mkdir(parents=True, exist_ok=True)
                current.write_bytes(names[name])
            groups = [
                {"id": "dashboard_header", "title": "سربرگ داشبورد", "description": "عنوان و دکمه داشبورد", "files": ["nava_journal/dashboard_header_layout.py"]},
                {"id": "recent_first_row", "title": "ردیف اول رویدادها", "description": "فقط ردیف اول کارت‌ها", "files": ["nava_journal/recent_card_first_row_layout.py"]},
            ]
            mandatory = ["nava_journal/pages.py", "nava_journal/version.py"]
            count = BUILD.make_patch(
                base, target, output, "0.4.3.1", "0.4.4", ["Selective layout patch"], groups, mandatory
            )
            self.assertEqual(count, 4)
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["always_apply_files"], mandatory)
                self.assertEqual([group["id"] for group in manifest["change_groups"]], ["dashboard_header", "recent_first_row"])
                grouped = {path for group in manifest["change_groups"] for path in group["files"]}
                self.assertEqual(grouped | set(mandatory), {item["path"] for item in manifest["files"]})


if __name__ == "__main__":
    unittest.main()
