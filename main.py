from __future__ import annotations

import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from nava_journal.db import Database
from nava_journal.repository import JournalRepository
from nava_journal.main_window import MainWindow
from nava_journal.theme import apply_theme


def main() -> int:
    QCoreApplication.setOrganizationName("NavaStudio")
    QCoreApplication.setApplicationName("NavaJournal")

    app = QApplication(sys.argv)
    app.setApplicationName("روزنگار")
    app.setStyle("Fusion")
    app.setFont(QFont("Tahoma", 10))

    # QSettings persists theme and preferences between launches.
    from PySide6.QtCore import QSettings
    settings = QSettings()

    # 0.6.0 applies a final one-time visual migration for existing Persian installs.
    # After migration the user may still change the general text preferences; the
    # sidebar and Memories page remain explicitly RTL regardless of that setting.
    if not settings.value("appearance/rtl_visual_migration_060", False, type=bool):
        settings.setValue("appearance/layout_direction", "rtl")
        settings.setValue("appearance/text_alignment", "right")
        settings.setValue("appearance/table_alignment", "auto")
        settings.setValue("appearance/background_highlight", "mint")
        settings.setValue("appearance/rtl_visual_migration_060", True)
        settings.sync()

    mode = settings.value("appearance/theme", "dark", type=str)
    font_family = settings.value("appearance/font", "auto", type=str)
    numeric_font = settings.value("appearance/numeric_font", "same", type=str)
    font_size = settings.value("appearance/font_size", 10, type=int)
    layout_direction = settings.value("appearance/layout_direction", "rtl", type=str)
    app.setProperty("nava_layout_direction", layout_direction)
    app.setProperty("nava_text_alignment", settings.value("appearance/text_alignment", "right", type=str))
    app.setProperty("nava_table_alignment", settings.value("appearance/table_alignment", "auto", type=str))
    app.setProperty("nava_digit_mode", settings.value("appearance/digit_mode", "latin", type=str))
    app.setProperty("nava_background_highlight", settings.value("appearance/background_highlight", "mint", type=str))
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if layout_direction == "rtl" else Qt.LayoutDirection.LeftToRight)
    apply_theme(
        app, mode, font_family, numeric_font, font_size,
        settings.value("appearance/background_highlight", "mint", type=str),
    )

    try:
        saved_database_path = settings.value("storage/database_path", "", type=str).strip()
        if saved_database_path and not Path(saved_database_path).is_file():
            QMessageBox.warning(
                None, "مسیر داده‌ها در دسترس نیست",
                "فایل پایگاه داده در مسیر انتخاب‌شده پیدا نشد. روزنگار با مسیر قبلی پیش‌فرض اجرا می‌شود؛ فایل داده‌های فعلی حذف نمی‌شود.",
            )
            settings.remove("storage/database_path")
            settings.sync()
            saved_database_path = ""
        database = Database(saved_database_path or None)
        repository = JournalRepository(database)
        window = MainWindow(repository, settings)
        window.show()
    except Exception as exc:
        QMessageBox.critical(None, "خطا در راه‌اندازی روزنگار", f"برنامه نتوانست راه‌اندازی شود.\n\n{exc}")
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
