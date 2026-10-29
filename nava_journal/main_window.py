from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QEasingCurve, QPoint, QPropertyAnimation, QSettings, QSize, Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut, QPixmap, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QTextEdit, QPlainTextEdit, QTableWidget,
    QVBoxLayout, QWidget, QSizeGrip,
)

from .dialogs import EntryDialog
from .auto_backup import application_root, create_close_backup
from .jalali import format_jalali, format_timestamp
from .pages import DashboardPage, JournalPage, MemoriesPage, SettingsPage
from .management import ManagementPage
from .theme import apply_theme, scale_local_stylesheets, normalize_theme, theme_colors
from .rtl import apply_rtl, confirm, show_error, show_info, show_warning
from .update_manager import UpdateError
from .update_ui import UpdateProgressDialog, UpdateSelectionDialog
from .version import APP_VERSION


class IntegratedTitleBar(QFrame):
    """A compact in-app title/toolbar for a frameless modern Windows-style window."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self._drag_offset = None
        self.setObjectName("appTitleBar")
        self.setProperty("navaPreserveLayoutDirection", True)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setFixedHeight(54)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 7, 15, 7)
        layout.setSpacing(6)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("windowCloseButton")
        self.close_button.setToolTip("بستن روزنگار")
        self.close_button.setFixedSize(34, 32)
        self.close_button.clicked.connect(window.close)

        self.maximize_button = QPushButton("□")
        self.maximize_button.setObjectName("windowControlButton")
        self.maximize_button.setToolTip("بزرگ‌نمایی / بازگردانی")
        self.maximize_button.setFixedSize(34, 32)
        self.maximize_button.clicked.connect(window.toggle_maximized)

        self.minimize_button = QPushButton("—")
        self.minimize_button.setObjectName("windowControlButton")
        self.minimize_button.setToolTip("کمینه‌کردن")
        self.minimize_button.setFixedSize(34, 32)
        self.minimize_button.clicked.connect(window.showMinimized)

        # With an LTR physical toolbar, Windows controls remain on the left while
        # the navigation toggle is anchored to the far right as requested.
        layout.addWidget(self.close_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.minimize_button)
        layout.addStretch(1)

        self.page_title = QLabel("روزنگار")
        self.page_title.setObjectName("appTitleText")
        self.page_title.setProperty("navaPreserveAlignment", True)
        self.page_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.page_title)

        self.sidebar_toggle = QPushButton("☰")
        self.sidebar_toggle.setObjectName("toolbarSidebarToggle")
        self.sidebar_toggle.setFixedSize(38, 34)
        self.sidebar_toggle.setToolTip("پنهان‌کردن منوی کناری")
        self.sidebar_toggle.setAccessibleName("نمایش یا پنهان‌کردن منوی کناری")
        self.sidebar_toggle.clicked.connect(window.toggle_sidebar)
        layout.addWidget(self.sidebar_toggle)

    def set_page_title(self, title: str) -> None:
        self.page_title.setText(f"روزنگار  /  {title}")

    def set_sidebar_visible_state(self, visible: bool) -> None:
        self.sidebar_toggle.setToolTip("پنهان‌کردن منوی کناری" if visible else "نمایش منوی کناری")
        self.sidebar_toggle.setProperty("expanded", bool(visible))
        self.sidebar_toggle.style().unpolish(self.sidebar_toggle)
        self.sidebar_toggle.style().polish(self.sidebar_toggle)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            self._drag_offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            handle = self._window.windowHandle()
            try:
                if handle is not None:
                    handle.startSystemMove()
            except (AttributeError, RuntimeError):
                pass
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._drag_offset = None
            else:
                self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximized()
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, repository, settings: QSettings) -> None:
        super().__init__()
        self._auto_close_backup_done = False
        # The native Windows title bar is replaced by an in-app toolbar. A size grip
        # and system move support preserve familiar window management behaviour.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.repository = repository
        self.database = repository.db
        self.settings = settings
        self.mode = normalize_theme(settings.value("appearance/theme", "dark", type=str))
        self._page_animation: QPropertyAnimation | None = None
        self._animated_page: QWidget | None = None
        self._sidebar_animation: QPropertyAnimation | None = None
        self._sidebar_visible = settings.value("navigation/sidebar_visible", True, type=bool)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_icon_labels: dict[str, QLabel] = {}
        self._page_titles = {
            "dashboard": "داشبورد",
            "memories": "مرور خاطرات",
            "journal": "ژورنال رویدادها",
            "archive": "بایگانی",
            "manage": "مدیریت داده‌ها",
            "settings": "تنظیمات و پشتیبان",
        }
        self.setWindowTitle("روزنگار | Nava Journal")
        self.setMinimumSize(1080, 640)
        self.resize(1280, 710)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        root = QWidget()
        root.setObjectName("mainRoot")
        root.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = IntegratedTitleBar(self)
        root_layout.addWidget(self.title_bar)

        body = QWidget()
        body.setObjectName("mainBody")
        body.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        body_layout = QHBoxLayout(body)
        body_layout.setDirection(QBoxLayout.Direction.LeftToRight)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setMaximumWidth(272 if self._sidebar_visible else 0)
        self.sidebar.setVisible(bool(self._sidebar_visible))
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(18, 24, 18, 22)
        side_layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setDirection(
            QBoxLayout.Direction.RightToLeft
            if self.settings.value("appearance/layout_direction", "rtl", type=str) == "rtl"
            else QBoxLayout.Direction.LeftToRight
        )
        brand_row.setSpacing(12)
        self.brand_mark = QLabel("ن")
        self.brand_mark.setObjectName("brandAvatar")
        self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_mark.setProperty("navaPreserveCenter", True)
        self.brand_mark.setFixedSize(50, 50)
        self._set_brand_avatar(str(self.settings.value("profile/avatar_path", "", type=str)))
        brand_text = QVBoxLayout()
        brand_name = QLabel("روزنگار")
        brand_name.setStyleSheet("font-size: 15pt; font-weight: 800;")
        brand_sub = QLabel("NAVA JOURNAL")
        brand_sub.setObjectName("muted")
        brand_sub.setStyleSheet("font-size: 8pt; letter-spacing: 1.5px;")
        brand_text.addWidget(brand_name)
        brand_text.addWidget(brand_sub)
        brand_row.addWidget(self.brand_mark)
        brand_row.addLayout(brand_text, 1)
        side_layout.addLayout(brand_row)
        side_layout.addSpacing(28)

        nav_label = QLabel("فضای کاری")
        nav_label.setObjectName("muted")
        nav_label.setStyleSheet("font-size: 9pt; padding-right: 10px;")
        side_layout.addWidget(nav_label)
        nav_items = [
            ("dashboard", "داشبورد"),
            ("memories", "مرور خاطرات"),
            ("journal", "ژورنال رویدادها"),
            ("archive", "بایگانی"),
            ("manage", "مدیریت داده‌ها"),
            ("settings", "تنظیمات و پشتیبان"),
        ]
        for key, label in nav_items:
            # Use an explicit RTL row instead of relying on platform-specific
            # QPushButton icon/text placement. This prevents Persian labels from
            # drifting to the left after a Qt style or layout-direction change.
            button = QPushButton()
            button.setObjectName("sidebarNavButton")
            button.setProperty("nav", True)
            button.setProperty("active", False)
            button.setProperty("navaTextAlign", "right")
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            button.setMinimumHeight(48)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_row = QHBoxLayout(button)
            nav_row.setContentsMargins(14, 3, 14, 3)
            nav_row.setSpacing(11)
            nav_row.setDirection(QBoxLayout.Direction.RightToLeft)
            icon_label = QLabel()
            icon_label.setFixedSize(20, 20)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setProperty("navaPreserveCenter", True)
            icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            icon_label.setPixmap(self._navigation_icon(key, self._navigation_icon_color(False)).pixmap(QSize(20, 20)))
            text_label = QLabel(label)
            text_label.setObjectName("sidebarNavLabel")
            text_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            # RTL order: first the text at the right edge, then the icon to its left.
            nav_row.addWidget(text_label, 1)
            nav_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
            button.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            side_layout.addWidget(button)
            self._nav_buttons[key] = button
            self._nav_icon_labels[key] = icon_label
        side_layout.addStretch(1)

        note = QFrame()
        note.setObjectName("surfaceCard")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(13, 12, 13, 12)
        note_title = QLabel("هر خاطره، بخشی از داستان تو")
        note_title.setObjectName("sidebarNoteTitle")
        note_body = QLabel("اینجا رویدادها، آدم‌ها و لحظه‌های مهم زندگی‌ات کنار هم می‌مانند.")
        note_body.setObjectName("muted")
        note_body.setWordWrap(True)
        note_layout.addWidget(note_title)
        note_layout.addWidget(note_body)
        side_layout.addWidget(note)
        version = QLabel(f"NAVA JOURNAL  ·  v{APP_VERSION}")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setProperty("navaPreserveCenter", True)
        version.setStyleSheet("font-size: 8pt; padding-top: 12px;")
        side_layout.addWidget(version)

        content = QFrame()
        content.setObjectName("contentPanel")
        content.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if self.settings.value("appearance/layout_direction", "rtl", type=str) == "rtl"
            else Qt.LayoutDirection.LeftToRight
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage(repository, settings=self.settings)
        self.memories_page = MemoriesPage(repository, settings=self.settings)
        self.journal_page = JournalPage(repository, archived=False, settings=self.settings)
        self.archive_page = JournalPage(repository, archived=True, settings=self.settings)
        self.management_page = ManagementPage(repository)
        self.settings_page = SettingsPage(
            self.database, self.mode, install_root=application_root(), app_version=APP_VERSION, settings=self.settings
        )
        self._install_rollback_panel()
        self.pages = {
            "dashboard": self.dashboard_page,
            "memories": self.memories_page,
            "journal": self.journal_page,
            "archive": self.archive_page,
            "manage": self.management_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack)

        body_layout.addWidget(content, 1)
        body_layout.addWidget(self.sidebar)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage(f"پایگاه داده آماده است · نسخه ساختار {self.database.schema_version()}")
        self.statusBar().setSizeGripEnabled(True)
        self._new_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self._new_shortcut.activated.connect(self.new_entry)
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.activated.connect(self._focus_search)

        self.dashboard_page.new_requested.connect(self.new_entry)
        self.dashboard_page.open_requested.connect(self.edit_entry)
        self.dashboard_page.view_all_requested.connect(lambda: self.navigate("journal"))
        self.dashboard_page.memories_requested.connect(lambda: self.navigate("memories"))
        self.memories_page.open_requested.connect(self.edit_entry)
        self.memories_page.new_requested.connect(self.new_entry)
        for page in (self.journal_page, self.archive_page):
            page.new_requested.connect(self.new_entry)
            page.edit_requested.connect(self.edit_entry)
            page.delete_requested.connect(self.delete_entry)
            page.favorite_requested.connect(self.toggle_favorite)
            page.archive_requested.connect(self.archive_entry)
            page.restore_requested.connect(self.restore_entry)
        self.settings_page.theme_changed.connect(self.change_theme)
        self.settings_page.background_highlight_changed.connect(self.change_background_highlight)
        self.settings_page.demo_data_seed_requested.connect(self.seed_demo_data)
        self.settings_page.demo_data_clear_requested.connect(self.clear_demo_data)
        self.settings_page.font_changed.connect(self.change_font)
        self.settings_page.numeric_font_changed.connect(self.change_numeric_font)
        self.settings_page.font_size_changed.connect(self.change_font_size)
        self.settings_page.avatar_changed.connect(self.change_avatar)
        self.settings_page.ui_preferences_changed.connect(self.change_ui_preferences)
        self.settings_page.backup_requested.connect(self.backup_database)
        self.settings_page.open_data_folder_requested.connect(self.open_data_folder)
        self.settings_page.export_requested.connect(self.export_csv)
        self.settings_page.integrity_requested.connect(self.check_database)
        self.settings_page.update_requested.connect(self.apply_update)
        self.settings_page.database_path_change_requested.connect(self._change_database_path)
        self.management_page.changed.connect(self._references_changed)

        # Apply global preferences first, then restore the dashboard/settings local layout islands.
        apply_rtl(self)
        self.enforce_sidebar_navigation_rtl()
        self.dashboard_page.enforce_local_layout()
        self.memories_page.enforce_local_layout()
        self.settings_page.enforce_font_size_layout()
        self.title_bar.set_sidebar_visible_state(bool(self._sidebar_visible))
        self.navigate("dashboard", animate=False)
        app = QApplication.instance()
        if app is not None:
            scale_local_stylesheets(app, int(self.settings.value("appearance/font_size", 10, type=int)))

    def enforce_sidebar_navigation_rtl(self) -> None:
        """Use a physical sidebar row plus an independently RTL Persian label.

        Pin each Persian navigation row to RTL. The text label is the first item in
        an explicitly RightToLeft box layout, so it sits at the sidebar's right edge;
        the icon follows to its left. The row never inherits a global LTR preference.
        """
        if not hasattr(self, "sidebar"):
            return
        self.sidebar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for key, button in self._nav_buttons.items():
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            button.setProperty("navaPreserveLayoutDirection", True)
            layout = button.layout()
            text_label = next((w for w in button.findChildren(QLabel) if w.objectName() == "sidebarNavLabel"), None)
            icon_label = self._nav_icon_labels.get(key)
            if isinstance(layout, QHBoxLayout):
                layout.setDirection(QBoxLayout.Direction.RightToLeft)
                layout.setContentsMargins(14, 3, 14, 3)
                layout.setSpacing(11)
                # In an RTL row the first child is physically right-most.
                if text_label is not None:
                    layout.removeWidget(text_label)
                if icon_label is not None:
                    layout.removeWidget(icon_label)
                if text_label is not None:
                    layout.addWidget(text_label, 1)
                if icon_label is not None:
                    layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
            if text_label is not None:
                text_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                text_label.setAlignment(right)
                text_label.setProperty("navaSidebarText", True)
                text_label.setProperty("navaPreserveAlignment", True)
                text_label.setMinimumWidth(0)
                text_label.setWordWrap(False)
            if icon_label is not None:
                icon_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon_label.setProperty("navaPreserveCenter", True)
        self.sidebar.updateGeometry()

    def _set_brand_avatar(self, image_path: str) -> None:
        """Load a user-selected avatar into the brand tile, falling back safely."""
        if not hasattr(self, "brand_mark"):
            return
        size = self.brand_mark.width() or 48
        path = Path(image_path) if image_path else None
        if path is not None and path.is_file():
            source = QPixmap(str(path))
            if not source.isNull():
                scaled = source.scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                crop_x = max(0, (scaled.width() - size) // 2)
                crop_y = max(0, (scaled.height() - size) // 2)
                crop = scaled.copy(crop_x, crop_y, size, size)
                masked = QPixmap(size, size)
                masked.fill(Qt.GlobalColor.transparent)
                painter = QPainter(masked)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                clipping = QPainterPath()
                clipping.addRoundedRect(0, 0, size, size, 15, 15)
                painter.setClipPath(clipping)
                painter.drawPixmap(0, 0, crop)
                painter.end()
                self.brand_mark.setPixmap(masked)
                self.brand_mark.setText("")
                self.brand_mark.setToolTip(str(path))
                self.brand_mark.setStyleSheet("background:transparent; border:1px solid rgba(148,163,184,0.48); border-radius:15px;")
                return
        self.brand_mark.setPixmap(QPixmap())
        self.brand_mark.setText("ن")
        self.brand_mark.setToolTip("نشان روزنگار؛ از تنظیمات می‌توانی آواتار انتخاب کنی.")
        palette = theme_colors(self.mode)
        accent_start = palette["accent"]
        accent_end = palette["success"]
        accent_text = palette["accent_text"]
        self.brand_mark.setStyleSheet(f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {accent_start},stop:1 {accent_end}); color:{accent_text}; border-radius:16px; font-size:23pt; font-weight:800;")

    def _navigation_icon_color(self, active: bool) -> str:
        palette = theme_colors(self.mode)
        return palette["accent"] if active else palette["muted"]

    @staticmethod
    def _navigation_icon(key: str, color: str) -> QIcon:
        """Render crisp, theme-aware line icons instead of dated Unicode glyphs."""
        paths = {
            "dashboard": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
            "memories": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.4 2"/><path d="M5 4.5 3.5 6"/>',
            "journal": '<path d="M6 3.5h9l3 3v14H6z"/><path d="M15 3.5v4h3"/><path d="M9 11h6M9 15h6"/>',
            "archive": '<path d="M3.5 6h17v4h-17z"/><path d="M5.5 10v10h13V10"/><path d="M9.5 14h5"/>',
            "manage": '<circle cx="7.5" cy="7.5" r="3"/><circle cx="16.5" cy="16.5" r="3"/><path d="m9.7 9.7 4.6 4.6"/><path d="M15.8 5.2h3v3"/>',
            "settings": '<path d="M4 7h8M16 7h4M4 17h4M12 17h8"/><circle cx="14" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
        }
        body = paths.get(key, paths["journal"])
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>'
        )
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def _set_active_nav(self, key: str) -> None:
        for nav_key, button in self._nav_buttons.items():
            active = nav_key == key
            button.setProperty("active", active)
            icon_label = self._nav_icon_labels.get(nav_key)
            if icon_label is not None:
                icon_label.setPixmap(self._navigation_icon(nav_key, self._navigation_icon_color(active)).pixmap(QSize(20, 20)))
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.title_bar.maximize_button.setText("□")
        else:
            self.showMaximized()
            self.title_bar.maximize_button.setText("❐")

    def toggle_sidebar(self) -> None:
        """Animate the right-hand navigation rail and persist the user's choice."""
        # Use the actual animated width, not only the last completed state, so a
        # second click during the transition reverses it instead of repeating it.
        target_visible = self.sidebar.width() <= 136
        animation = self._sidebar_animation
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        self._sidebar_animation = None
        self._sidebar_visible = target_visible
        self.settings.setValue("navigation/sidebar_visible", target_visible)
        self.settings.sync()

        if target_visible:
            self.sidebar.setVisible(True)
            self.sidebar.setMaximumWidth(0)
            start_width, end_width = 0, 272
        else:
            self.sidebar.setVisible(True)
            self.sidebar.setMaximumWidth(272)
            start_width, end_width = self.sidebar.width(), 0

        animation = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        animation.setDuration(210)
        animation.setStartValue(start_width)
        animation.setEndValue(end_width)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def finish() -> None:
            if self._sidebar_animation is not animation:
                return
            self._sidebar_visible = target_visible
            self.sidebar.setMaximumWidth(272 if target_visible else 0)
            self.sidebar.setVisible(target_visible)
            self.settings.setValue("navigation/sidebar_visible", target_visible)
            self.settings.sync()
            self.title_bar.set_sidebar_visible_state(target_visible)
            self._sidebar_animation = None
            animation.deleteLater()

        animation.finished.connect(finish)
        self._sidebar_animation = animation
        animation.start()

    def navigate(self, key: str, animate: bool = True) -> None:
        """Switch pages with a small slide animation without nested graphics effects.

        Older builds faded entire pages using QGraphicsOpacityEffect while dashboard
        cards had their own effects. Some Qt/Windows combinations crash when such a
        page is rebuilt and selected again. A position-only animation avoids that
        unsafe nested-effect path while keeping navigation animated.
        """
        if key not in self.pages:
            return
        page = self.pages[key]
        self._set_active_nav(key)
        self.title_bar.set_page_title(self._page_titles.get(key, "روزنگار"))
        if self.stack.currentWidget() is page:
            if key == "dashboard":
                self.dashboard_page.refresh()
            elif key == "memories":
                self.memories_page.refresh()
            return

        old_animation = self._page_animation
        old_page = self._animated_page
        if old_animation is not None:
            old_animation.stop()
            if old_page is not None:
                try:
                    old_page.move(0, 0)
                except RuntimeError:
                    pass
            old_animation.deleteLater()
        self._page_animation = None
        self._animated_page = None

        self.stack.setCurrentWidget(page)
        page.move(0, 0)
        if animate:
            start_pos = QPoint(0, 12)
            end_pos = QPoint(0, 0)
            page.move(start_pos)
            animation = QPropertyAnimation(page, b"pos", self)
            animation.setDuration(190)
            animation.setStartValue(start_pos)
            animation.setEndValue(end_pos)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.finished.connect(lambda p=page, a=animation: self._finish_page_transition(p, a))
            self._page_animation = animation
            self._animated_page = page
            animation.start()

        if key == "dashboard":
            self.dashboard_page.refresh()
        elif key == "memories":
            self.memories_page.refresh()
        elif key == "journal":
            self.journal_page.refresh()
        elif key == "archive":
            self.archive_page.refresh()
        elif key == "manage":
            self.management_page.refresh()

    def _finish_page_transition(self, page: QWidget, animation: QPropertyAnimation) -> None:
        """Normalize the page only if this animation is still the current transition."""
        if self._page_animation is not animation:
            return
        try:
            if page is self.stack.currentWidget():
                page.move(0, 0)
        except RuntimeError:
            pass
        self._page_animation = None
        self._animated_page = None
        animation.deleteLater()

    def _focus_search(self) -> None:
        self.navigate("journal")
        self.journal_page.search_edit.setFocus()

    def refresh_all(self) -> None:
        self.dashboard_page.refresh()
        self.dashboard_page.enforce_local_layout()
        self.memories_page.refresh()
        self.journal_page.refresh()
        self.archive_page.refresh()
        self.settings_page.enforce_font_size_layout()
        app = QApplication.instance()
        if app is not None:
            size = int(self.settings.value("appearance/font_size", 10, type=int))
            scale_local_stylesheets(app, size)

    def _references_changed(self) -> None:
        """Refresh reference dropdowns after categories or people are managed."""
        self.journal_page.refresh_reference_filters(refresh=False)
        self.archive_page.refresh_reference_filters(refresh=False)
        self.management_page.refresh()
        self.refresh_all()
        self.statusBar().showMessage("فهرست دسته‌بندی‌ها، اشخاص و برچسب‌ها به‌روز شد.", 3500)

    def new_entry(self) -> None:
        dialog = EntryDialog(
            self.repository.categories(), self.repository.people(), tags=self.repository.tags(),
            repository=self.repository, parent=self
        )
        dialog.references_changed.connect(self._references_changed)
        app = QApplication.instance()
        if app is not None:
            scale_local_stylesheets(app, int(self.settings.value("appearance/font_size", 10, type=int)))
        if dialog.exec() != EntryDialog.DialogCode.Accepted:
            return
        try:
            entry_id = self.repository.save_entry(dialog.payload(), dialog.attachment_paths())
        except Exception as exc:
            show_error(self, "ثبت انجام نشد", f"اطلاعات ذخیره نشد.\n\n{exc}")
            return
        self.journal_page.refresh_reference_filters(refresh=False)
        self.archive_page.refresh_reference_filters(refresh=False)
        self.refresh_all()
        self.navigate("journal")
        self.statusBar().showMessage(f"رویداد با شناسه {entry_id} ذخیره شد.", 5000)

    def edit_entry(self, entry_id: int) -> None:
        entry = self.repository.get_entry(entry_id)
        if entry is None:
            show_warning(self, "رکورد پیدا نشد", "این رویداد وجود ندارد یا حذف شده است.")
            self.refresh_all()
            return
        dialog = EntryDialog(
            self.repository.categories(), self.repository.people(), tags=self.repository.tags(),
            repository=self.repository, entry=entry, parent=self
        )
        dialog.references_changed.connect(self._references_changed)
        app = QApplication.instance()
        if app is not None:
            scale_local_stylesheets(app, int(self.settings.value("appearance/font_size", 10, type=int)))
        if dialog.exec() != EntryDialog.DialogCode.Accepted:
            return
        try:
            self.repository.save_entry(dialog.payload(), dialog.attachment_paths())
        except Exception as exc:
            show_error(self, "ذخیره تغییرات ناموفق بود", f"تغییرات ذخیره نشد.\n\n{exc}")
            return
        self.journal_page.refresh_reference_filters(refresh=False)
        self.archive_page.refresh_reference_filters(refresh=False)
        self.refresh_all()
        self.statusBar().showMessage("تغییرات رویداد ذخیره شد.", 5000)

    def delete_entry(self, entry_id: int) -> None:
        entry = self.repository.get_entry(entry_id)
        if entry is None:
            return
        if not confirm(
            self, "حذف دائمی رویداد",
            f"«{entry['title']}» برای همیشه از پایگاه داده حذف شود؟\n\nفایل‌های اصلی حذف نمی‌شوند؛ فقط ارتباط آن‌ها با رویداد از بین می‌رود.",
        ):
            return
        self.repository.delete_entry(entry_id)
        self.refresh_all()
        self.statusBar().showMessage("رویداد حذف شد.", 4000)

    def toggle_favorite(self, entry_id: int) -> None:
        self.repository.toggle_favorite(entry_id)
        self.refresh_all()

    def archive_entry(self, entry_id: int) -> None:
        self.repository.archive_entry(entry_id)
        self.refresh_all()
        self.statusBar().showMessage("رویداد به بایگانی منتقل شد.", 4000)

    def restore_entry(self, entry_id: int) -> None:
        self.repository.unarchive_entry(entry_id)
        self.refresh_all()
        self.statusBar().showMessage("رویداد از بایگانی بازیابی شد.", 4000)

    def _apply_saved_theme(self) -> None:
        selected_font = self.settings.value("appearance/font", "auto", type=str)
        numeric_font = self.settings.value("appearance/numeric_font", "same", type=str)
        font_size = int(self.settings.value("appearance/font_size", 10, type=int))
        apply_theme(
            QApplication.instance(), self.mode, selected_font, numeric_font, font_size,
            str(self.settings.value("appearance/background_highlight", "mint", type=str)),
        )
        for key, button in self._nav_buttons.items():
            active = button.property("active") is True
            icon_label = self._nav_icon_labels.get(key)
            if icon_label is not None:
                icon_label.setPixmap(self._navigation_icon(key, self._navigation_icon_color(active)).pixmap(QSize(20, 20)))
        avatar_path = str(self.settings.value("profile/avatar_path", "", type=str))
        self._set_brand_avatar(avatar_path)
        self.settings_page._display_avatar_preview(avatar_path)
        self.refresh_all()
        self.enforce_sidebar_navigation_rtl()
        self.memories_page.enforce_local_layout()

    def change_theme(self, mode: str) -> None:
        self.mode = normalize_theme(mode)
        self.settings.setValue("appearance/theme", self.mode)
        self._apply_saved_theme()
        self.statusBar().showMessage("پوسته ذخیره شد.", 3000)

    def change_background_highlight(self, preset: str) -> None:
        from .theme import normalize_highlight
        selected = normalize_highlight(preset)
        self.settings.setValue("appearance/background_highlight", selected)
        app = QApplication.instance()
        if app is not None:
            app.setProperty("nava_background_highlight", selected)
        self.settings.sync()
        self._apply_saved_theme()
        self.statusBar().showMessage("هایلایت پس‌زمینه ذخیره شد.", 3000)

    def seed_demo_data(self) -> None:
        status = self.repository.demo_data_status()
        if status.get("seeded"):
            show_info(self, "دادهٔ آزمایشی موجود است", f"بستهٔ آزمایشی قبلاً افزوده شده است؛ {status.get('count', 0)} رکورد از آن هنوز وجود دارد. برای ساخت دوباره، ابتدا همان بسته را حذف کن.")
            return
        if not confirm(
            self, "افزودن ۵۰ رکورد آزمایشی",
            "۵۰ رویداد ساختگی با تاریخ‌های پراکنده در دو سال گذشته، برچسب‌ها، اشخاص و چند فایل پیوست به همین دیتابیس اضافه می‌شود.\n\n"
            "یادداشت‌های واقعی تو و فایل‌های اصلی حذف یا بازنویسی نمی‌شوند. هر زمان خواستی فقط رکوردهای این بسته را می‌توانی حذف کنی. ادامه می‌دهی؟",
        ):
            return
        try:
            result = self.repository.seed_demo_data()
        except Exception as exc:
            show_error(self, "ساخت دادهٔ آزمایشی ناموفق بود", f"دادهٔ آزمایشی کامل نشد.\n\n{exc}")
            return
        if result.get("already_seeded"):
            show_info(self, "دادهٔ آزمایشی موجود است", "بستهٔ آزمایشی قبلاً به این پایگاه داده اضافه شده است.")
            return
        self.journal_page.refresh_reference_filters(refresh=False)
        self.archive_page.refresh_reference_filters(refresh=False)
        self.management_page.refresh()
        self.refresh_all()
        self.enforce_sidebar_navigation_rtl()
        show_info(self, "دادهٔ آزمایشی آماده است", "۵۰ رویداد ساختگی به تاریخ‌های دو سال گذشته اضافه شد. چند مورد دارای پیوست واقعی نمونه، برچسب، شخص، اهمیت، وضعیت پیگیری و وضعیت بایگانی‌اند. با جست‌وجوی «داده آزمایشی» می‌توانی تمام رکوردهای این بسته را پیدا کنی.")

    def clear_demo_data(self) -> None:
        status = self.repository.demo_data_status()
        if not status.get("seeded"):
            show_info(self, "بسته‌ای برای حذف نیست", "هیچ بستهٔ دادهٔ آزمایشی شناخته‌شده‌ای در این پایگاه داده وجود ندارد.")
            return
        if not confirm(
            self, "حذف فقط داده‌های آزمایشی",
            f"{status.get('count', 0)} رکورد متعلق به بستهٔ آزمایشی و پیوست‌های ساختگی آن حذف می‌شوند.\n\n"
            "هیچ رکورد عادی یا فایل اصلی تو حذف نمی‌شود. ادامه می‌دهی؟",
        ):
            return
        try:
            result = self.repository.clear_demo_data()
        except Exception as exc:
            show_error(self, "حذف دادهٔ آزمایشی ناموفق بود", f"بستهٔ آزمایشی حذف نشد.\n\n{exc}")
            return
        self.journal_page.refresh_reference_filters(refresh=False)
        self.archive_page.refresh_reference_filters(refresh=False)
        self.management_page.refresh()
        self.refresh_all()
        show_info(self, "داده‌های آزمایشی حذف شدند", f"{result.get('removed', 0)} رکورد آزمایشی و فایل‌های نمونهٔ ساخته‌شده حذف شدند. داده‌های دیگر دست‌نخورده ماندند.")

    def change_font(self, family: str) -> None:
        self.settings.setValue("appearance/font", family or "auto")
        self._apply_saved_theme()
        self.statusBar().showMessage("فونت رابط کاربری ذخیره شد.", 3000)

    def change_numeric_font(self, family: str) -> None:
        self.settings.setValue("appearance/numeric_font", family or "same")
        self._apply_saved_theme()
        self.statusBar().showMessage("فونت اعداد و جدول ژورنال ذخیره شد.", 3000)

    def change_font_size(self, size: int) -> None:
        size = max(8, min(18, int(size)))
        self.settings.setValue("appearance/font_size", size)
        self.settings.sync()
        self._apply_saved_theme()
        self.statusBar().showMessage(f"اندازه فونت کل برنامه روی {size} تنظیم شد.", 2500)

    def change_avatar(self, image_path: str) -> None:
        if image_path and not Path(image_path).is_file():
            show_warning(self, "تصویر پیدا نشد", "فایل آواتار در مسیر ذخیره‌شده پیدا نشد.")
            image_path = ""
        if image_path:
            self.settings.setValue("profile/avatar_path", image_path)
        else:
            self.settings.remove("profile/avatar_path")
        self.settings.sync()
        self._set_brand_avatar(image_path)
        self.statusBar().showMessage("تصویر آواتار به‌روزرسانی شد.", 2500)

    def change_ui_preferences(
        self, layout_direction: str, text_alignment: str, digit_mode: str, table_alignment: str
    ) -> None:
        layout_direction = layout_direction if layout_direction in ("rtl", "ltr") else "rtl"
        text_alignment = text_alignment if text_alignment in ("right", "left", "start", "center") else "right"
        digit_mode = digit_mode if digit_mode in ("latin", "persian") else "latin"
        table_alignment = table_alignment if table_alignment in ("auto", "right", "left", "center") else "auto"
        self.settings.setValue("appearance/layout_direction", layout_direction)
        self.settings.setValue("appearance/text_alignment", text_alignment)
        self.settings.setValue("appearance/digit_mode", digit_mode)
        self.settings.setValue("appearance/table_alignment", table_alignment)
        app = QApplication.instance()
        if app is not None:
            app.setProperty("nava_layout_direction", layout_direction)
            app.setProperty("nava_text_alignment", text_alignment)
            app.setProperty("nava_digit_mode", digit_mode)
            app.setProperty("nava_table_alignment", table_alignment)
            app.setLayoutDirection(
                Qt.LayoutDirection.RightToLeft if layout_direction == "rtl" else Qt.LayoutDirection.LeftToRight
            )
            selected_font = self.settings.value("appearance/font", "auto", type=str)
            numeric_font = self.settings.value("appearance/numeric_font", "same", type=str)
            font_size = int(self.settings.value("appearance/font_size", 10, type=int))
            apply_theme(
                app, self.mode, selected_font, numeric_font, font_size,
                str(self.settings.value("appearance/background_highlight", "mint", type=str)),
            )
        apply_rtl(self)
        self.enforce_sidebar_navigation_rtl()
        self.refresh_all()
        # Refresh reconstructs table cells and recent cards; reapply the chosen settings.
        apply_rtl(self)
        self.dashboard_page.enforce_local_layout()
        self.memories_page.enforce_local_layout()
        self.enforce_sidebar_navigation_rtl()
        self.settings_page.enforce_font_size_layout()
        self.statusBar().showMessage("جهت چیدمان، تراز متن و جدول و شکل اعداد اعمال شد.", 3500)

    def _install_rollback_panel(self) -> None:
        """Add rollback controls without disturbing the existing SettingsPage layout code."""
        settings_page = self.settings_page
        content = getattr(getattr(settings_page, "scroll_area", None), "widget", lambda: None)()
        layout = content.layout() if content is not None else None
        if layout is None:
            return
        card = QFrame(content)
        card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(8)
        title = QLabel("بازگشت به نسخه قبلی")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "اگر ظاهر یا رفتار آخرین به‌روزرسانی را نپسندیدی، فایل‌های برنامه را به نسخه پیش از همان به‌روزرسانی برگردان. "
            "اطلاعات جدید ژورنال به‌طور پیش‌فرض حفظ می‌شود."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        self.rollback_status_label = QLabel("")
        self.rollback_status_label.setObjectName("updateStatus")
        self.rollback_status_label.setWordWrap(True)
        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.RightToLeft)
        self.rollback_button = QPushButton("↶  بازگردانی نسخه قبلی")
        self.rollback_button.setProperty("danger", True)
        self.rollback_button.setMinimumHeight(38)
        self.rollback_button.clicked.connect(self.rollback_update)
        actions.addWidget(self.rollback_button)
        actions.addStretch(1)
        card_layout.addWidget(title)
        card_layout.addWidget(description)
        card_layout.addWidget(self.rollback_status_label)
        card_layout.addLayout(actions)
        layout.insertWidget(min(3, layout.count()), card)
        self._refresh_rollback_panel()

    def _refresh_rollback_panel(self) -> None:
        if not hasattr(self, "rollback_button"):
            return
        manager = self.settings_page.update_manager
        allowed, detail, status = manager.rollback_capability()
        self.rollback_button.setEnabled(allowed)
        self.rollback_status_label.setText(detail)
        if status and status.get("target_version"):
            self.rollback_button.setToolTip(f"بازگشت از نسخه {status.get('target_version')} به نسخه {status.get('base_version', 'قبلی')}")
        else:
            self.rollback_button.setToolTip(detail)

    def apply_update(self, archive_path: str) -> None:
        manager = self.settings_page.update_manager
        try:
            manifest = manager.inspect_update(archive_path)
        except UpdateError as exc:
            show_warning(self, "بسته به‌روزرسانی رد شد", str(exc))
            return

        selection_dialog = UpdateSelectionDialog(manifest, self)
        if selection_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_group_ids = selection_dialog.selected_group_ids()
        try:
            selected_records, selected_groups = manager.selected_file_records(manifest, selected_group_ids)
        except UpdateError as exc:
            show_warning(self, "انتخاب تغییرات معتبر نیست", str(exc))
            return

        notes = manifest.get("release_notes") or ["توضیحی برای این انتشار ثبت نشده است."]
        group_lines = "\n".join(f"  ✓ {group['title']}" for group in selected_groups)
        file_list = "\n".join(f"  • {record['path']}" for record in selected_records)
        if not confirm(
            self, "تأیید به‌روزرسانی انتخاب‌شده",
            f"نسخه {manifest['version']} آماده نصب است.\n\n"
            f"مجموعه‌های انتخاب‌شده:\n{group_lines}\n\n"
            f"تعداد فایل‌های قابل جایگزینی: {len(selected_records)}\n"
            f"توضیحات انتشار: {'؛ '.join(str(note) for note in notes)}\n\n"
            f"فایل‌های تغییرکرده:\n{file_list}\n\n"
            "از پایگاه داده پشتیبان گرفته می‌شود. فقط مجموعه‌های تیک‌خورده اعمال می‌شوند؛ برای بازگشت به این تصمیم، نسخه پشتیبان فایل‌ها نگه‌داری می‌شود. ادامه می‌دهی؟"
        ):
            return
        try:
            pending_path, prepared_manifest = manager.prepare_update(archive_path, self.database, selected_group_ids)
        except Exception as exc:
            show_error(self, "آماده‌سازی به‌روزرسانی ناموفق بود", str(exc))
            return

        self._update_progress_dialog = UpdateProgressDialog(prepared_manifest["version"], len(prepared_manifest["files"]), self)
        self._update_progress_dialog.show()
        QApplication.processEvents()
        try:
            manager.launch_worker(pending_path)
        except Exception as exc:
            self._update_progress_dialog.close()
            show_error(self, "راه‌اندازی عامل به‌روزرسانی ناموفق بود", str(exc))
            return
        self._update_progress_dialog.mark_ready_to_close()
        QTimer.singleShot(800, self._exit_for_update)

    def rollback_update(self) -> None:
        manager = self.settings_page.update_manager
        allowed, reason, status = manager.rollback_capability()
        if not allowed or status is None:
            show_warning(self, "بازگشت در دسترس نیست", reason)
            self._refresh_rollback_panel()
            return
        previous_version = status.get("base_version", "نسخه قبلی")
        updated_version = status.get("target_version", self.settings_page.app_version)
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("بازگشت به نسخه قبلی")
        message.setText(
            f"فایل‌های برنامه از نسخه {updated_version} به نسخه {previous_version} بازمی‌گردند.\n\n"
            "به‌طور پیش‌فرض، یادداشت‌ها و رویدادهایی که بعد از به‌روزرسانی ثبت کرده‌ای حفظ می‌شوند."
        )
        message.setInformativeText(
            "فقط در صورتی گزینه پایگاه داده را فعال کن که می‌خواهی دیتابیس دقیقاً به زمان پیش از به‌روزرسانی برگردد؛ "
            "در آن حالت رویدادهای ثبت‌شده بعد از آن زمان در دیتابیس فعال باقی نمی‌مانند. یک پشتیبان ایمنی از دیتابیس فعلی هم ساخته می‌شود."
        )
        restore_database_checkbox = QCheckBox("پایگاه داده را هم به زمان پیش از به‌روزرسانی برگردان")
        message.setCheckBox(restore_database_checkbox)
        message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        message.setDefaultButton(QMessageBox.StandardButton.No)
        message.button(QMessageBox.StandardButton.Yes).setText("بازگردانی")
        message.button(QMessageBox.StandardButton.No).setText("انصراف")
        if message.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            pending_path, rollback_manifest = manager.prepare_rollback(
                self.database, restore_database=restore_database_checkbox.isChecked()
            )
        except Exception as exc:
            show_error(self, "آماده‌سازی بازگشت ناموفق بود", str(exc))
            return

        self._update_progress_dialog = UpdateProgressDialog(
            rollback_manifest["version"], len(rollback_manifest["files"]), self, operation="rollback"
        )
        self._update_progress_dialog.show()
        QApplication.processEvents()
        try:
            manager.launch_worker(pending_path)
        except Exception as exc:
            self._update_progress_dialog.close()
            show_error(self, "راه‌اندازی عامل بازگشت ناموفق بود", str(exc))
            return
        self._update_progress_dialog.mark_ready_to_close()
        QTimer.singleShot(800, self._exit_for_update)

    def _exit_for_update(self) -> None:
        if hasattr(self, "_update_progress_dialog"):
            self._update_progress_dialog.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _change_database_path(self, destination: str, overwrite: bool = False) -> None:
        target = Path(destination).expanduser().resolve()
        current = self.database.path.resolve()
        if target == current:
            show_info(self, "مسیر بدون تغییر", "این فایل همین حالا پایگاه داده فعال است.")
            return
        try:
            self.statusBar().showMessage("در حال انتقال ایمن پایگاه داده…")
            QApplication.processEvents()
            moved = self.database.move_to_and_switch(target, overwrite=bool(overwrite))
            if moved.resolve() == (self.database.app_data_dir / "journal.sqlite3").resolve():
                self.settings.remove("storage/database_path")
            else:
                self.settings.setValue("storage/database_path", str(moved))
            self.settings.sync()
            self.settings_page.set_database_path(moved)
            self.statusBar().showMessage("مسیر داده‌ها با موفقیت تغییر کرد.", 5000)
            self.refresh_all()
            show_info(
                self, "تغییر مسیر انجام شد",
                f"پایگاه داده با موفقیت به مسیر جدید منتقل شد و از این پس همین فایل فعال است:\n{moved}\n\nفایل اصلی از مسیر قبلی برداشته شده است. اگر فایل مقصدی پیش‌تر وجود داشت و جایگزین شد، نسخه قبلی مقصد با نام زمان‌دار نگه‌داری شده است.",
            )
        except Exception as exc:
            self.statusBar().clearMessage()
            show_error(self, "انتقال مسیر ناموفق بود", f"روزنگار تلاش کرد فایل را به‌صورت ایمن منتقل کند. در صورت بروز خطا، مسیر قبلی به‌عنوان مسیر فعال نگه داشته می‌شود.\n\n{exc}")

    def backup_database(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = str(Path.home() / "Documents" / f"NavaJournal_backup_{stamp}.sqlite3")
        destination, _ = QFileDialog.getSaveFileName(
            self, "ذخیره نسخه پشتیبان", default_path,
            "SQLite database (*.sqlite3 *.db);;All files (*.*)",
        )
        if not destination:
            return
        if not destination.lower().endswith((".sqlite3", ".db")):
            destination += ".sqlite3"
        try:
            path = self.database.backup_to(destination)
        except Exception as exc:
            show_error(self, "پشتیبان‌گیری ناموفق بود", str(exc))
            return
        show_info(self, "نسخه پشتیبان آماده شد", f"نسخه پشتیبان ذخیره شد:\n{path}")

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.database.path.parent)))

    def export_csv(self) -> None:
        destination, _ = QFileDialog.getSaveFileName(
            self, "خروجی گرفتن از ژورنال", str(Path.home() / "Documents" / "NavaJournal_export.csv"),
            "CSV UTF-8 (*.csv)",
        )
        if not destination:
            return
        if not destination.lower().endswith(".csv"):
            destination += ".csv"
        entries = self.repository.list_entries(archived=False)
        try:
            with open(destination, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "شناسه", "تاریخ شمسی", "عنوان", "دسته‌بندی", "شخص", "وضعیت پیگیری", "اهمیت",
                    "برچسب‌ها", "یادداشت", "زمان ایجاد", "آخرین تغییر", "پیوست‌ها",
                ])
                follow_labels = {"none": "بدون پیگیری", "pending": "نیازمند پیگیری", "in_progress": "در حال انجام", "done": "انجام شده"}
                importance_labels = {"normal": "عادی", "important": "مهم", "critical": "فوری / بحرانی"}
                for entry in entries:
                    full = self.repository.get_entry(entry["id"]) or entry
                    attachments = full.get("attachments", [])
                    compact_jalali_date = format_jalali(entry["event_date"], persian_digits=False)
                    writer.writerow([
                        entry["id"], compact_jalali_date, entry["title"],
                        entry["category_name"] or "بدون دسته", entry.get("person_name") or "",
                        follow_labels.get(entry.get("follow_up_status", "none"), entry.get("follow_up_status", "none")),
                        importance_labels.get(entry.get("importance", "normal"), entry.get("importance", "normal")),
                        full.get("tag_names") or "", entry["body"],
                        format_timestamp(entry["created_at"], persian_digits=False),
                        format_timestamp(entry["updated_at"], persian_digits=False),
                        " | ".join(item["path"] for item in attachments),
                    ])
        except OSError as exc:
            show_error(self, "خروجی ناموفق بود", str(exc))
            return
        show_info(self, "خروجی آماده شد", f"اطلاعات در فایل زیر ذخیره شد:\n{destination}")

    def check_database(self) -> None:
        try:
            result = self.database.quick_check()
        except Exception as exc:
            show_error(self, "بررسی پایگاه داده ناموفق بود", str(exc))
            return
        if result == "ok":
            show_info(self, "پایگاه داده سالم است", "SQLite نتیجه PRAGMA quick_check را با مقدار ok برگرداند.")
        else:
            show_warning(self, "نیاز به بررسی", f"نتیجه بررسی پایگاه داده:\n{result}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Save a verified, timestamped snapshot without altering the live database."""
        if self._auto_close_backup_done:
            event.accept()
            return
        try:
            backup_path, used_fallback = create_close_backup(self.database)
            self.settings.setValue("backup/last_automatic_path", str(backup_path))
            self.settings.setValue("backup/last_automatic_at", datetime.now().astimezone().isoformat(timespec="seconds"))
            self.settings.setValue("backup/last_automatic_used_fallback", bool(used_fallback))
            self.settings.sync()
            logging.getLogger(__name__).info("Automatic close backup saved: %s", backup_path)
            self._auto_close_backup_done = True
            if used_fallback:
                QMessageBox.information(
                    self,
                    "پشتیبان خودکار ساخته شد",
                    "پوشه اصلی برنامه قابل نوشتن نبود؛ نسخه پشتیبان در مسیر جایگزین ذخیره شد:\n\n"
                    f"{backup_path}",
                )
            event.accept()
        except Exception as exc:
            logging.getLogger(__name__).exception("Automatic close backup failed")
            answer = QMessageBox.question(
                self,
                "پشتیبان خودکار ساخته نشد",
                "هنگام ساخت نسخه پشتیبان خودکار خطا رخ داد. بهتر است قبل از خروج دوباره تلاش شود.\n\n"
                f"جزئیات: {exc}\n\nآیا با وجود این خطا از برنامه خارج می‌شوی؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._auto_close_backup_done = True
                event.accept()
            else:
                event.ignore()
