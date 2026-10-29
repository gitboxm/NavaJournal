from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QVBoxLayout
    _QT_AVAILABLE = True
except Exception:
    _QT_AVAILABLE = False


class WorkerTimeline:
    """Independent updater window that remains visible while the main app is closed."""

    def __init__(self, target_version: str, file_count: int) -> None:
        self.app = None
        self.window = None
        self.timeline = None
        self.progress = None
        self.status = None
        self.step_count = 0
        self.max_steps = max(9, file_count + 8)
        if not _QT_AVAILABLE:
            return
        try:
            self.app = QApplication.instance() or QApplication([])
            self.app.setApplicationName("Nava Journal Updater")
            self.app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.app.setStyle("Fusion")
            self.app.setFont(QFont("Tahoma", 10))
            self.window = QDialog()
            self.window.setWindowTitle("به‌روزرسانی روزنگار")
            self.window.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.window.setMinimumSize(660, 470)
            self.window.resize(720, 520)
            self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.window.setStyleSheet("""
                QDialog { background:#0B1020; color:#EDF2FA; }
                QLabel { color:#EDF2FA; background:transparent; }
                QLabel#muted { color:#9AA9BE; }
                QLabel#headline { font-size:18pt; font-weight:800; color:#F1F4FC; }
                QLabel#version { color:#B8A4FF; font-size:11pt; font-weight:700; }
                QFrame#card { background:#111B2E; border:1px solid #27364D; border-radius:14px; }
                QListWidget { background:#111B2E; border:1px solid #27364D; border-radius:10px; padding:7px; color:#EDF2FA; }
                QListWidget::item { background:#17243A; border:1px solid #27364D; border-radius:8px; padding:8px; margin:3px 0; }
                QProgressBar { border:1px solid #27364D; border-radius:6px; background:#17243A; color:#EDF2FA; text-align:center; min-height:18px; }
                QProgressBar::chunk { background:#A78BFA; border-radius:5px; }
            """)
            outer = QVBoxLayout(self.window)
            outer.setContentsMargins(22, 20, 22, 20)
            outer.setSpacing(12)
            head = QHBoxLayout()
            brand = QLabel("ن")
            brand.setFixedSize(44, 44)
            brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
            brand.setStyleSheet("background:#A78BFA; color:#151225; border-radius:13px; font-size:22pt; font-weight:800;")
            text_col = QVBoxLayout()
            headline = QLabel("روزنگار در حال به‌روزرسانی است")
            headline.setObjectName("headline")
            headline.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            subtitle = QLabel("فقط فایل‌های تغییریافته جایگزین می‌شوند؛ اطلاعات شخصی و پایگاه داده حفظ می‌شوند.")
            subtitle.setObjectName("muted")
            subtitle.setWordWrap(True)
            subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            version = QLabel(f"نسخه مقصد: {target_version}  ·  {file_count} فایل")
            version.setObjectName("version")
            version.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text_col.addWidget(headline)
            text_col.addWidget(subtitle)
            text_col.addWidget(version)
            head.addWidget(brand)
            head.addLayout(text_col, 1)
            outer.addLayout(head)
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(8)
            self.timeline = QListWidget()
            self.timeline.setMinimumHeight(260)
            card_layout.addWidget(self.timeline)
            outer.addWidget(card, 1)
            self.progress = QProgressBar()
            self.progress.setRange(0, self.max_steps)
            self.progress.setValue(0)
            outer.addWidget(self.progress)
            self.status = QLabel("در حال راه‌اندازی عامل به‌روزرسانی…")
            self.status.setObjectName("muted")
            self.status.setWordWrap(True)
            self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            outer.addWidget(self.status)
            self.window.show()
            self.process_events()
        except Exception:
            self.app = self.window = self.timeline = self.progress = self.status = None

    def process_events(self) -> None:
        if self.app is not None:
            try:
                self.app.processEvents()
            except Exception:
                pass

    def add(self, state: str, title: str, detail: str) -> None:
        self.step_count += 1
        if self.timeline is not None:
            try:
                symbol = "✓" if state in {"done", "completed", "restarted", "app_closed", "file_replaced", "files_replaced"} else ("!" if state in {"failed", "restart_failed", "preparation_failed"} else "◉")
                item = QListWidgetItem(f"{symbol}  {title}\n    {detail}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.timeline.addItem(item)
                self.timeline.scrollToBottom()
                self.progress.setValue(min(self.max_steps, self.step_count))
                self.status.setText(detail)
                self.process_events()
            except Exception:
                pass

    def finish(self, success: bool, message: str, seconds: float = 1.8) -> None:
        if self.window is None or self.app is None:
            return
        try:
            self.status.setText(message)
            self.progress.setValue(self.max_steps if success else min(self.max_steps, max(1, self.step_count)))
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                self.process_events()
                time.sleep(0.05)
            self.window.close()
            self.process_events()
        except Exception:
            pass


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def safe_target(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or "\x00" in relative:
        raise ValueError(f"Unsafe patch path: {relative!r}")
    parts = PurePosixPath(relative).parts
    if PurePosixPath(relative).is_absolute() or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe patch path: {relative!r}")
    if relative != "main.py" and not relative.startswith("nava_journal/"):
        raise ValueError(f"Disallowed patch path: {relative!r}")
    target = root.joinpath(*parts)
    resolved_parent = target.parent.resolve()
    if not resolved_parent.is_relative_to(root.resolve()):
        raise ValueError(f"Patch path escapes application directory: {relative!r}")
    if target.exists() and not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Target symlink escapes application directory: {relative!r}")
    return target


def launch_application(pending: dict, root: Path) -> subprocess.Popen:
    command = [pending["python_executable"], *pending["restart_args"]]
    if os.name == "nt":
        process = subprocess.Popen(command, cwd=str(root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        process = subprocess.Popen(command, cwd=str(root), start_new_session=True)

    # Reap quick test/utility children and keep a handle while the real GUI stays open.
    # The daemon waiter never blocks the updater from exiting after relaunching the app.
    threading.Thread(target=process.wait, name="nava-restart-reaper", daemon=True).start()
    return process


def run(pending_path: Path) -> int:
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    root = Path(pending["install_root"]).resolve()
    stage = Path(pending["stage_dir"]).resolve()
    backup = Path(pending["backup_dir"]).resolve()
    status_path = Path(pending["status_path"]).resolve()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    timeline = status.setdefault("timeline", [])
    ui = WorkerTimeline(str(pending.get("target_version", "—")), len(pending.get("files", [])))
    for previous in timeline:
        ui.add(str(previous.get("state", "done")), str(previous.get("title", "")), str(previous.get("detail", "")))

    def event(state: str, title: str, detail: str) -> None:
        timeline.append({"state": state, "title": title, "detail": detail, "time": datetime.now().astimezone().isoformat(timespec="seconds")})
        status["state"] = state
        atomic_json(status_path, status)
        ui.add(state, title, detail)

    event("waiting_for_app", "انتظار بسته‌شدن برنامه", "این پنجره مستقل باقی می‌ماند؛ پس از بسته‌شدن روزنگار، عملیات آغاز می‌شود.")
    pid = int(pending.get("parent_pid", -1))
    deadline = time.monotonic() + 120
    while pid > 0 and is_process_running(pid):
        if time.monotonic() >= deadline:
            message = "پس از دو دقیقه برنامه اصلی هنوز فعال بود. هیچ فایلی تغییر نکرد؛ برنامه را ببند و دوباره اجرا کن."
            event("failed", "برنامه بسته نشد", message)
            ui.finish(False, message, 3.0)
            return 2
        ui.process_events()
        time.sleep(0.25)

    replaced: list[tuple[Path, Path | None]] = []
    try:
        backup.mkdir(parents=True, exist_ok=True)
        event("app_closed", "برنامه بسته شد", "اکنون جایگزینی فایل‌های کد در حالت امن انجام می‌شود.")
        for relative in pending["files"]:
            target = safe_target(root, relative)
            source = safe_target(stage, relative)
            if not source.is_file():
                raise FileNotFoundError(f"Staged patch file is missing: {relative}")
            old_backup: Path | None = None
            if target.exists():
                old_backup = backup.joinpath(*PurePosixPath(relative).parts)
                old_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, old_backup)
            replaced.append((target, old_backup))
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_target = target.with_name(target.name + ".nava-update-tmp")
            shutil.copy2(source, temp_target)
            os.replace(temp_target, target)
            event("file_replaced", "فایل جایگزین شد", f"{relative} با نسخه تأییدشده جایگزین شد؛ فایل‌های دیگر دست‌نخورده ماندند.")
        event("files_replaced", "فایل‌های تغییرکرده جایگزین شدند", f"{len(replaced)} فایل به‌روزرسانی شد؛ فایل‌های دیگر برنامه دست‌نخورده باقی ماندند.")
        status["state"] = "completed"
        status["completed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        event("completed", "به‌روزرسانی کامل شد", f"روزنگار از نسخه {pending['base_version']} به نسخه {pending['target_version']} ارتقا یافت.")
    except Exception as exc:
        rollback_errors: list[str] = []
        for target, old_backup in reversed(replaced):
            try:
                if old_backup and old_backup.exists():
                    temp_target = target.with_name(target.name + ".nava-rollback-tmp")
                    shutil.copy2(old_backup, temp_target)
                    os.replace(temp_target, target)
                elif target.exists():
                    target.unlink()
            except Exception as rollback_exc:
                rollback_errors.append(f"{target.name}: {rollback_exc}")
        detail = f"خطا هنگام جایگزینی فایل‌ها: {exc}"
        if rollback_errors:
            detail += " | خطاهای بازگردانی: " + "; ".join(rollback_errors)
        event("failed", "به‌روزرسانی شکست خورد", detail)
        try:
            launch_application(pending, root)
        except Exception as launch_exc:
            event("restart_failed", "اجرای دوباره ناموفق بود", str(launch_exc))
        ui.finish(False, detail, 3.0)
        return 1

    try:
        launch_application(pending, root)
        event("restarted", "اجرای دوباره برنامه", "نسخه جدید روزنگار اجرا شد. جزئیات در تنظیمات ← به‌روزرسانی قابل مشاهده است.")
        ui.finish(True, "به‌روزرسانی موفق بود؛ برنامه جدید اجرا شده است.", 2.0)
    except Exception as exc:
        message = f"فایل‌ها به‌روز شدند، اما اجرای دوباره ناموفق بود. برنامه را دستی اجرا کن. جزئیات: {exc}"
        event("restart_failed", "اجرای دوباره ناموفق بود", message)
        ui.finish(False, message, 3.0)
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", required=True)
    args = parser.parse_args()
    return run(Path(args.pending).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
