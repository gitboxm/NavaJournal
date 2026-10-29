from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .version import APP_ID, APP_VERSION

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 150 * 1024 * 1024
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
_ALLOWED_SUFFIXES = {".py", ".json", ".qss", ".svg", ".png", ".webp", ".ico", ".txt"}
_SUCCESS_STATES = {"restarted", "completed"}


class UpdateError(ValueError):
    """A safe, user-displayable error from patch inspection or preparation."""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = value.split(".")
    if not parts or len(parts) > 4 or any(not part.isdigit() for part in parts):
        raise UpdateError(f"شماره نسخه نامعتبر است: {value!r}")
    return tuple(int(part) for part in parts)


def _versions_equal(first: str, second: str) -> bool:
    a, b = _version_tuple(first), _version_tuple(second)
    return a + (0,) * (4 - len(a)) == b + (0,) * (4 - len(b))


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise UpdateError("مسیر یکی از فایل‌های بسته معتبر نیست.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise UpdateError(f"مسیر ناامن در بسته به‌روزرسانی: {value}")
    normalized = path.as_posix()
    if normalized == "main.py":
        return normalized
    if not normalized.startswith("nava_journal/"):
        raise UpdateError(f"به‌روزرسانی اجازه تغییر این مسیر را ندارد: {normalized}")
    if "__pycache__" in path.parts or path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise UpdateError(f"نوع فایل برای به‌روزرسانی مجاز نیست: {normalized}")
    return normalized


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class UpdateManager:
    """File-level updater with selectable feature groups and one-step rollback.

    The manifest assigns each changed path to exactly one feature group, except
    technical `always_apply_files` (normally just version metadata). Shared files
    are intentionally grouped together so a user cannot install half a feature.
    """

    def __init__(
        self,
        install_root: str | Path,
        data_dir: str | Path,
        current_version: str = APP_VERSION,
    ) -> None:
        self.install_root = Path(install_root).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.current_version = current_version
        self.updates_dir = self.data_dir / "updates"
        self.status_path = self.updates_dir / "last_update.json"

    def inspect_update(self, archive_path: str | Path) -> dict[str, Any]:
        path = Path(archive_path).resolve()
        if not path.is_file() or path.suffix.lower() != ".zip":
            raise UpdateError("یک فایل ZIP به‌روزرسانی انتخاب کن.")
        size = path.stat().st_size
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            raise UpdateError("اندازه بسته خارج از محدوده مجاز است.")
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                if len(names) != len(set(names)):
                    raise UpdateError("بسته شامل نام فایل تکراری است و رد شد.")
                if "manifest.json" not in names:
                    raise UpdateError("فایل manifest.json در بسته پیدا نشد؛ این ZIP یک بسته به‌روزرسانی معتبر نیست.")
                manifest_info = archive.getinfo("manifest.json")
                if manifest_info.file_size > MAX_MANIFEST_BYTES:
                    raise UpdateError("فایل مشخصات بسته بیش از حد بزرگ است.")
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                if not isinstance(manifest, dict):
                    raise UpdateError("ساختار manifest معتبر نیست.")
                if manifest.get("format_version") != 1 or manifest.get("app_id") != APP_ID:
                    raise UpdateError("این بسته برای روزنگار ساخته نشده یا نسخه قالب آن پشتیبانی نمی‌شود.")
                release_notes = manifest.get("release_notes", [])
                if not isinstance(release_notes, list) or any(not isinstance(note, str) for note in release_notes):
                    raise UpdateError("ساختار توضیحات انتشار معتبر نیست.")
                base_version = str(manifest.get("base_version", ""))
                target_version = str(manifest.get("version", ""))
                if not _versions_equal(base_version, self.current_version):
                    raise UpdateError(
                        f"این بسته برای نسخه {base_version} ساخته شده، اما نسخه فعلی برنامه {self.current_version} است. "
                        "بسته مناسب نسخه فعلی را انتخاب کن."
                    )
                if _version_tuple(target_version) <= _version_tuple(self.current_version):
                    raise UpdateError("نسخه مقصد باید از نسخه فعلی جدیدتر باشد.")
                file_records = manifest.get("files")
                if not isinstance(file_records, list) or not file_records:
                    raise UpdateError("این بسته هیچ فایل تغییریافته‌ای ندارد.")
                expected_names = {"manifest.json"}
                seen_paths: set[str] = set()
                total_unpacked = 0
                verified_files: list[dict[str, Any]] = []
                for record in file_records:
                    if not isinstance(record, dict):
                        raise UpdateError("فهرست فایل‌های بسته خراب است.")
                    relative = _safe_relative_path(record.get("path"))
                    if relative in seen_paths:
                        raise UpdateError(f"یک مسیر در manifest تکرار شده است: {relative}")
                    seen_paths.add(relative)
                    archive_name = f"files/{relative}"
                    expected_names.add(archive_name)
                    try:
                        info = archive.getinfo(archive_name)
                    except KeyError as exc:
                        raise UpdateError(f"فایل {relative} داخل ZIP وجود ندارد.") from exc
                    if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                        raise UpdateError(f"اندازه یا نوع فایل مجاز نیست: {relative}")
                    unix_mode = (info.external_attr >> 16) & 0o170000
                    if unix_mode == 0o120000:
                        raise UpdateError(f"فایل پیوندی (symlink) مجاز نیست: {relative}")
                    total_unpacked += info.file_size
                    if total_unpacked > MAX_UNPACKED_BYTES:
                        raise UpdateError("حجم بازشده بسته بیش از حد مجاز است.")
                    content = archive.read(archive_name)
                    expected_hash = str(record.get("sha256", "")).lower()
                    expected_size = record.get("size")
                    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
                        raise UpdateError(f"اندازه ثبت‌شده برای فایل معتبر نیست: {relative}")
                    if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
                        raise UpdateError(f"هش SHA-256 برای فایل معتبر نیست: {relative}")
                    if len(content) != expected_size or _sha256(content) != expected_hash:
                        raise UpdateError(f"تأیید صحت فایل ناموفق بود: {relative}")
                    verified_files.append({"path": relative, "size": len(content), "sha256": expected_hash})
                actual_files = {name for name in names if not name.endswith("/")}
                if actual_files != expected_names:
                    extra = sorted(actual_files - expected_names)
                    missing = sorted(expected_names - actual_files)
                    detail = ", ".join(extra or missing)
                    raise UpdateError(f"ZIP شامل فایل‌های پیش‌بینی‌نشده یا ناقص است: {detail}")
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f"امکان خواندن بسته به‌روزرسانی وجود ندارد: {exc}") from exc

        file_paths = {record["path"] for record in verified_files}
        always_raw = manifest.get("always_apply_files", [])
        if not isinstance(always_raw, list):
            raise UpdateError("فهرست فایل‌های فنیِ همراه به‌روزرسانی معتبر نیست.")
        always_apply: list[str] = []
        for value in always_raw:
            relative = _safe_relative_path(value)
            if relative not in file_paths or relative in always_apply:
                raise UpdateError(f"فایل فنیِ همراه در فهرست بسته به‌صورت معتبر تعریف نشده است: {relative}")
            always_apply.append(relative)

        groups_raw = manifest.get("change_groups")
        if groups_raw is None:
            # Backward compatibility for old-style patches: all changed files make
            # one coherent, selectable group.
            groups = [{
                "id": "all",
                "title": "تمام تغییرات این نسخه",
                "description": "این بسته فهرست تغییرات تفکیک‌شده ندارد؛ تمام فایل‌های آن یک مجموعه واحد هستند.",
                "files": sorted(file_paths - set(always_apply)),
            }]
            if not groups[0]["files"]:
                groups[0]["files"] = sorted(file_paths)
                always_apply = []
        else:
            if not isinstance(groups_raw, list) or not groups_raw:
                raise UpdateError("گروه‌های تغییرات باید یک فهرست غیرخالی باشند.")
            groups = []
            group_ids: set[str] = set()
            assigned = set(always_apply)
            for raw_group in groups_raw:
                if not isinstance(raw_group, dict):
                    raise UpdateError("یکی از گروه‌های تغییرات ساختار معتبری ندارد.")
                group_id = raw_group.get("id")
                title = raw_group.get("title")
                description = raw_group.get("description", "")
                paths_raw = raw_group.get("files")
                if (not isinstance(group_id, str) or not group_id or len(group_id) > 80
                        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in group_id)):
                    raise UpdateError("شناسه یکی از گروه‌های تغییرات معتبر نیست.")
                if group_id in group_ids:
                    raise UpdateError(f"شناسه گروه تکراری است: {group_id}")
                if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
                    raise UpdateError(f"عنوان یا توضیح گروه {group_id} معتبر نیست.")
                if not isinstance(paths_raw, list) or not paths_raw:
                    raise UpdateError(f"گروه {title} هیچ فایل تغییریافته‌ای ندارد.")
                paths: list[str] = []
                for value in paths_raw:
                    relative = _safe_relative_path(value)
                    if relative not in file_paths:
                        raise UpdateError(f"گروه {title} به فایلی ارجاع می‌دهد که در بسته نیست: {relative}")
                    if relative in assigned:
                        raise UpdateError(f"فایل {relative} به چند گروه تعلق گرفته یا تکراری است.")
                    assigned.add(relative)
                    paths.append(relative)
                group_ids.add(group_id)
                groups.append({"id": group_id, "title": title.strip(), "description": description.strip(), "files": paths})
            if assigned != file_paths:
                missing_groups = sorted(file_paths - assigned)
                unknown = sorted(assigned - file_paths)
                raise UpdateError(
                    "همه فایل‌ها باید دقیقاً به یک گروه یا فهرست فنی تعلق داشته باشند. "
                    f"فایل‌های بدون گروه: {', '.join(missing_groups) or 'ندارد'}؛ نامعتبر: {', '.join(unknown) or 'ندارد'}"
                )

        manifest["files"] = verified_files
        manifest["change_groups"] = groups
        manifest["always_apply_files"] = always_apply
        manifest["archive_path"] = str(path.resolve())
        manifest["current_version"] = self.current_version
        manifest["total_bytes"] = sum(item["size"] for item in verified_files)
        return manifest

    def selected_file_records(self, manifest: dict[str, Any], selected_group_ids: list[str] | set[str] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups = manifest["change_groups"]
        valid_ids = {group["id"] for group in groups}
        if selected_group_ids is None:
            selected_ids = valid_ids
        else:
            selected_ids = set(selected_group_ids)
            unknown = selected_ids - valid_ids
            if unknown:
                raise UpdateError(f"گروه انتخاب‌شده در این بسته وجود ندارد: {', '.join(sorted(unknown))}")
        if not selected_ids:
            raise UpdateError("برای ادامه، دست‌کم یک گروه تغییرات را انتخاب کن؛ در غیر این صورت به‌روزرسانی را لغو کن.")
        selected_groups = [group for group in groups if group["id"] in selected_ids]
        selected_paths = set(manifest.get("always_apply_files", []))
        for group in selected_groups:
            selected_paths.update(group["files"])
        selected_records = [record for record in manifest["files"] if record["path"] in selected_paths]
        if not selected_records:
            raise UpdateError("پس از انتخاب گروه‌ها هیچ فایلی برای به‌روزرسانی باقی نماند.")
        return selected_records, selected_groups

    def read_last_status(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_status(self, status: dict[str, Any]) -> None:
        _atomic_json(self.status_path, status)

    def rollback_capability(self) -> tuple[bool, str, dict[str, Any] | None]:
        status = self.read_last_status()
        if not status:
            return False, "هنوز سابقه‌ای برای بازگشت وجود ندارد.", None
        if status.get("operation") == "rollback" or status.get("state") == "rolled_back":
            return False, "آخرین عملیات بازگشت بوده است؛ برای جلوگیری از بازگشت تکراری، ابتدا یک به‌روزرسانی جدید نصب کن.", status
        if status.get("state") not in _SUCCESS_STATES:
            return False, "آخرین به‌روزرسانی با موفقیت کامل نشده است.", status
        target_version = str(status.get("target_version", ""))
        try:
            if not _versions_equal(target_version, self.current_version):
                return False, f"نسخه ثبت‌شده ({target_version}) با نسخه فعلی ({self.current_version}) یکسان نیست.", status
        except UpdateError:
            return False, "نسخه ثبت‌شده در گزارش به‌روزرسانی معتبر نیست.", status
        backup_dir = Path(str(status.get("backup_dir", ""))).resolve()
        files = status.get("files")
        if not backup_dir.is_dir() or not isinstance(files, list) or not files:
            return False, "پشتیبان فایل‌های نسخه قبلی پیدا نشد؛ امکان بازگشت امن وجود ندارد.", status
        try:
            safe_files = [_safe_relative_path(item) for item in files]
        except UpdateError as exc:
            return False, f"فهرست فایل‌های نسخه قبلی معتبر نیست: {exc}", status
        if not any(backup_dir.joinpath(*PurePosixPath(item).parts).is_file() for item in safe_files):
            return False, "هیچ فایل قبلی در پوشه پشتیبان پیدا نشد.", status
        return True, f"امکان بازگشت از نسخه {self.current_version} به نسخه {status.get('base_version', 'قبلی')} وجود دارد.", status

    def prepare_update(self, archive_path: str | Path, database, selected_group_ids: list[str] | set[str] | None = None) -> tuple[Path, dict[str, Any]]:
        manifest = self.inspect_update(archive_path)
        selected_records, selected_groups = self.selected_file_records(manifest, selected_group_ids)
        update_id = f"{manifest['version']}_{uuid.uuid4().hex[:8]}"
        stage_dir = self.updates_dir / "staging" / update_id
        backup_dir = self.updates_dir / "file_backups" / update_id
        db_backup_dir = self.updates_dir / "database_backups"
        db_backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        database_backup = db_backup_dir / f"before_{self.current_version}_to_{manifest['version']}_{stamp}_{uuid.uuid4().hex[:5]}.sqlite3"
        selected_paths = [item["path"] for item in selected_records]
        status: dict[str, Any] = {
            "app_id": APP_ID,
            "operation": "update",
            "base_version": self.current_version,
            "target_version": manifest["version"],
            "state": "preparing",
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "release_notes": list(manifest.get("release_notes") or []),
            "selected_groups": [{"id": group["id"], "title": group["title"]} for group in selected_groups],
            "always_apply_files": list(manifest.get("always_apply_files", [])),
            "files": selected_paths,
            "backup_dir": str(backup_dir),
            "timeline": [],
        }
        self._write_status(status)
        try:
            status["timeline"].append({"state": "done", "title": "بررسی بسته", "detail": f"{len(manifest['files'])} فایل و هش SHA-256 تأیید شد."})
            status["timeline"].append({"state": "done", "title": "انتخاب تغییرات", "detail": f"{len(selected_groups)} گروه و {len(selected_paths)} فایل برای اعمال انتخاب شد."})
            database.backup_to(database_backup)
            status["database_backup"] = str(database_backup)
            status["timeline"].append({"state": "done", "title": "پشتیبان پایگاه داده", "detail": "قبل از تغییر کدها یک نسخه مستقل از SQLite ساخته شد."})
            stage_dir.mkdir(parents=True, exist_ok=False)
            with zipfile.ZipFile(Path(archive_path).resolve(), "r") as archive:
                for record in selected_records:
                    relative = record["path"]
                    content = archive.read(f"files/{relative}")
                    target = stage_dir.joinpath(*PurePosixPath(relative).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            status["timeline"].append({"state": "done", "title": "آماده‌سازی فایل‌های انتخاب‌شده", "detail": "فقط فایل‌های متعلق به گروه‌های انتخابی وارد مرحله اعمال شدند."})
            status.update({"state": "ready_to_restart", "stage_dir": str(stage_dir), "backup_dir": str(backup_dir)})
            self._write_status(status)
            pending = {
                "app_id": APP_ID,
                "operation": "update",
                "base_version": self.current_version,
                "target_version": manifest["version"],
                "install_root": str(self.install_root),
                "data_dir": str(self.data_dir),
                "stage_dir": str(stage_dir),
                "backup_dir": str(backup_dir),
                "status_path": str(self.status_path),
                "files": selected_paths,
                "parent_pid": os.getpid(),
                "python_executable": sys.executable,
                "restart_args": [str(self.install_root / "main.py")],
                "release_notes": list(manifest.get("release_notes") or []),
                "database_backup": str(database_backup),
            }
            pending_path = self.updates_dir / f"pending_{update_id}.json"
            _atomic_json(pending_path, pending)
            status["pending_file"] = str(pending_path)
            self._write_status(status)
            return pending_path, {**manifest, "files": selected_records, "selected_groups": selected_groups}
        except Exception as exc:
            status["state"] = "preparation_failed"
            status["error"] = str(exc)
            status["timeline"].append({"state": "error", "title": "آماده‌سازی ناموفق", "detail": str(exc)})
            self._write_status(status)
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise

    def prepare_rollback(self, database, restore_database: bool = False) -> tuple[Path, dict[str, Any]]:
        allowed, reason, last_status = self.rollback_capability()
        if not allowed or last_status is None:
            raise UpdateError(reason)
        original_backup = Path(str(last_status.get("backup_dir", ""))).resolve()
        files = [_safe_relative_path(value) for value in last_status["files"]]
        old_db_backup_text = str(last_status.get("database_backup", ""))
        old_db_backup = Path(old_db_backup_text).resolve() if old_db_backup_text else None
        if restore_database and (old_db_backup is None or not old_db_backup.is_file()):
            raise UpdateError("پشتیبان پایگاه داده قبل از به‌روزرسانی پیدا نشد؛ می‌توانی فقط فایل‌های برنامه را بازگردانی کنی.")

        self.updates_dir.mkdir(parents=True, exist_ok=True)
        history_dir = self.updates_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        history_path = history_dir / f"before_rollback_{last_status.get('target_version', 'version')}_{stamp}_{uuid.uuid4().hex[:4]}.json"
        shutil.copy2(self.status_path, history_path)

        rollback_id = f"rollback_{uuid.uuid4().hex[:10]}"
        stage_dir = self.updates_dir / "staging" / rollback_id
        rollback_backup_dir = self.updates_dir / "file_backups" / rollback_id
        db_backup_dir = self.updates_dir / "database_backups"
        db_backup_dir.mkdir(parents=True, exist_ok=True)
        safety_db = db_backup_dir / f"before_rollback_{self.current_version}_{stamp}_{uuid.uuid4().hex[:5]}.sqlite3"
        database.backup_to(safety_db)
        stage_dir.mkdir(parents=True, exist_ok=False)
        source_backups = 0
        for relative in files:
            old_file = original_backup.joinpath(*PurePosixPath(relative).parts)
            if old_file.is_file():
                staged_file = stage_dir.joinpath(*PurePosixPath(relative).parts)
                staged_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_file, staged_file)
                source_backups += 1
        if source_backups == 0:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise UpdateError("فایل‌های پشتیبان نسخه قبلی قابل بازیابی نیستند.")

        previous_version = str(last_status.get("base_version", ""))
        rolled_back_version = str(last_status.get("target_version", self.current_version))
        status: dict[str, Any] = {
            "app_id": APP_ID,
            "operation": "rollback",
            "base_version": self.current_version,
            "target_version": previous_version,
            "rollback_of_version": rolled_back_version,
            "state": "preparing_rollback",
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": files,
            "backup_dir": str(rollback_backup_dir),
            "rollback_source_backup_dir": str(original_backup),
            "restore_database": bool(restore_database),
            "database_backup": str(old_db_backup) if old_db_backup else "",
            "rollback_safety_database_backup": str(safety_db),
            "history_snapshot": str(history_path),
            "timeline": [
                {"state": "done", "title": "بررسی نسخه قبلی", "detail": f"فایل‌های نسخه {previous_version} از پشتیبان تأییدشده آماده شدند."},
                {"state": "done", "title": "پشتیبان پیش از بازگشت", "detail": "از نسخه فعلی پایگاه داده و فایل‌های فعلی برنامه برای بازیابی خطا پشتیبان گرفته می‌شود."},
            ],
        }
        self._write_status(status)
        pending = {
            "app_id": APP_ID,
            "operation": "rollback",
            "base_version": self.current_version,
            "target_version": previous_version,
            "install_root": str(self.install_root),
            "data_dir": str(self.data_dir),
            "stage_dir": str(stage_dir),
            "backup_dir": str(rollback_backup_dir),
            "status_path": str(self.status_path),
            "files": files,
            "parent_pid": os.getpid(),
            "python_executable": sys.executable,
            "restart_args": [str(self.install_root / "main.py")],
            "restore_database": bool(restore_database),
            "database_path": str(database.path),
            "database_backup": str(old_db_backup) if old_db_backup else "",
            "rollback_safety_database_backup": str(safety_db),
        }
        pending_path = self.updates_dir / f"pending_{rollback_id}.json"
        _atomic_json(pending_path, pending)
        status["pending_file"] = str(pending_path)
        self._write_status(status)
        manifest = {
            "version": previous_version,
            "base_version": self.current_version,
            "files": [{"path": item} for item in files],
            "operation": "rollback",
            "rollback_of_version": rolled_back_version,
            "restore_database": bool(restore_database),
        }
        return pending_path, manifest

    def launch_worker(self, pending_path: str | Path) -> subprocess.Popen:
        # This worker is part of the patchable application package. The root-level
        # worker remains as a bootstrap bridge for versions before 0.4.3.1.
        worker = self.install_root / "nava_journal" / "update_worker.py"
        if not worker.is_file():
            raise UpdateError("عامل به‌روزرسانی جدید پیدا نشد؛ یک‌بار بسته کامل نسخه را نصب کن.")
        log_path = self.updates_dir / "worker.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-I", str(worker), "--pending", str(Path(pending_path).resolve())]
        kwargs: dict[str, Any] = {"cwd": str(self.install_root), "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            with open(log_path, "ab") as log:
                return subprocess.Popen(command, stdout=log, stderr=log, **kwargs)
        kwargs["start_new_session"] = True
        with open(log_path, "ab") as log:
            return subprocess.Popen(command, stdout=log, stderr=log, **kwargs)
