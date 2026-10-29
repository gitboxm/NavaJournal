from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QFrame, QHBoxLayout, QBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget, QHeaderView,
)
from .rtl import apply_rtl, confirm, show_info, show_warning
from .theme import contrast_foreground


class ReferenceItemDialog(QDialog):
    """Small editor shared by the category and person managers."""

    def __init__(self, kind: str, item: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.item = item or {}
        self.color_value = str(self.item.get("color") or ("#8B7CF6" if kind == "category" else "#38BDF8"))
        is_category = kind == "category"
        is_person = kind == "person"
        kind_label = "دسته‌بندی" if is_category else ("شخص" if is_person else "برچسب")
        self.setWindowTitle((f"ویرایش {kind_label}") if item else (f"{kind_label} جدید"))
        self.setMinimumWidth(520)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(13)
        heading = QLabel(self.windowTitle())
        heading.setObjectName("pageTitle")
        outer.addWidget(heading)

        name_label = QLabel("نام دسته‌بندی" if is_category else ("نام شخص" if is_person else "نام برچسب"))
        self.name_edit = QLineEdit(str(self.item.get("name", "")))
        self.name_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.name_edit.setPlaceholderText("نام را وارد کن...")
        outer.addWidget(name_label)
        outer.addWidget(self.name_edit)

        if is_person:
            notes_label = QLabel("یادداشت درباره شخص  ·  اختیاری")
            self.notes_edit = QTextEdit()
            self.notes_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.notes_edit.setPlainText(str(self.item.get("notes", "")))
            self.notes_edit.setMaximumHeight(130)
            self.notes_edit.setPlaceholderText("نکته یا اطلاعات تکمیلی، در صورت نیاز...")
            outer.addWidget(notes_label)
            outer.addWidget(self.notes_edit)
        else:
            self.notes_edit = None

        color_row = QHBoxLayout()
        color_label = QLabel("رنگ نشان")
        color_row.addWidget(color_label)
        color_row.addStretch(1)
        self.color_button = QPushButton("انتخاب رنگ")
        self.color_button.clicked.connect(self.choose_color)
        color_row.addWidget(self.color_button)
        self.color_preview = QLabel(self.color_value)
        self.color_preview.setMinimumWidth(100)
        self.color_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.color_preview.setProperty("navaPreserveCenter", True)
        color_row.addWidget(self.color_preview)
        outer.addLayout(color_row)
        self._refresh_color_preview()

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("انصراف")
        save = QPushButton("ذخیره")
        save.setProperty("primary", True)
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_if_valid)
        footer.addWidget(cancel)
        footer.addWidget(save)
        outer.addLayout(footer)
        apply_rtl(self)
        self.name_edit.setFocus()

    def choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color_value), self, "انتخاب رنگ")
        if color.isValid():
            self.color_value = color.name().upper()
            self._refresh_color_preview()

    def _refresh_color_preview(self) -> None:
        self.color_preview.setText(self.color_value)
        self.color_preview.setStyleSheet(
            f"background:{self.color_value}; color:{contrast_foreground(self.color_value)}; border-radius:8px; padding:7px; font-weight:700;"
        )

    def _accept_if_valid(self) -> None:
        if not self.name_edit.text().strip():
            show_warning(self, "نام لازم است", "لطفاً یک نام وارد کن.")
            self.name_edit.setFocus()
            return
        self.accept()

    def payload(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip() if self.notes_edit is not None else "",
            "color": self.color_value,
        }


class ReferencePanel(QWidget):
    changed = Signal()

    def __init__(self, repository, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.kind = kind
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        is_category = kind == "category"
        is_person = kind == "person"
        is_tag = kind == "tag"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 14, 12, 12)
        outer.setSpacing(13)
        explainer = QLabel(
            "دسته‌بندی‌ها را می‌توانی تغییر نام بدهی یا رنگشان را عوض کنی. رویدادها حذف نمی‌شوند؛ اگر دسته را حذف کنی، فقط ارتباط دسته از رویدادها برداشته می‌شود."
            if is_category else (
            "اشخاص را یک‌بار تعریف کن و در فرم هر رویداد به‌صورت اختیاری انتخاب کن. حذف شخص، خود رویدادها را حذف نمی‌کند."
            if is_person else
            "برچسب‌ها را مدیریت کن؛ هر رویداد می‌تواند چند برچسب داشته باشد. حذف برچسب، متن رویدادها را حذف نمی‌کند؛ فقط اتصال همان برچسب پاک می‌شود."
            )
        )
        explainer.setObjectName("muted")
        explainer.setWordWrap(True)
        outer.addWidget(explainer)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["دسته‌بندی", "رنگ"] if is_category else (["شخص", "یادداشت"] if is_person else ["برچسب", "رنگ"]))
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeaderItem(0).setToolTip("برای مرتب‌سازی کلیک کن")
        self.table.horizontalHeaderItem(1).setToolTip("برای مرتب‌سازی کلیک کن")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        outer.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setDirection(QBoxLayout.Direction.RightToLeft)
        self.add_button = QPushButton("＋ افزودن")
        self.add_button.setProperty("primary", True)
        self.edit_button = QPushButton("ویرایش انتخاب‌شده")
        self.delete_button = QPushButton("حذف انتخاب‌شده")
        self.delete_button.setProperty("danger", True)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        self.add_button.clicked.connect(self.add_item)
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.refresh()

    def _items(self) -> list[dict]:
        if self.kind == "category":
            return self.repository.categories()
        if self.kind == "person":
            return self.repository.people()
        return self.repository.tags()

    def refresh(self) -> None:
        rows = self._items()
        sort_column = self.table.horizontalHeader().sortIndicatorSection()
        sort_order = self.table.horizontalHeader().sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            first = QTableWidgetItem(item["name"])
            first.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            first.setData(Qt.ItemDataRole.UserRole, item["id"])
            self.table.setItem(row_index, 0, first)
            if self.kind in ("category", "tag"):
                second = QTableWidgetItem(item.get("color", ""))
                second.setToolTip("رنگ نمایشی مورد")
                second.setForeground(QColor(item.get("color", "#8B7CF6")))
            else:
                second = QTableWidgetItem(item.get("notes", ""))
            second.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_index, 1, second)
        self.table.setSortingEnabled(True)
        if sort_column >= 0:
            self.table.sortItems(sort_column, sort_order)
        self.table.clearSelection()

    def selected_item(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        cell = self.table.item(row, 0)
        item_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if not item_id:
            return None
        return next((item for item in self._items() if item["id"] == int(item_id)), None)

    def add_item(self) -> None:
        dialog = ReferenceItemDialog(self.kind, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.payload()
        try:
            if self.kind == "category":
                self.repository.add_category(data["name"], data["color"])
            elif self.kind == "person":
                self.repository.add_person(data["name"], data["notes"], data["color"])
            else:
                self.repository.add_tag(data["name"], data["color"])
        except (sqlite3.IntegrityError, ValueError) as exc:
            show_warning(self, "ثبت انجام نشد", self._friendly_error(exc))
            return
        self.refresh()
        self.changed.emit()

    def edit_selected(self) -> None:
        item = self.selected_item()
        if not item:
            show_info(self, "انتخاب مورد", "ابتدا یک مورد را از فهرست انتخاب کن.")
            return
        dialog = ReferenceItemDialog(self.kind, item=item, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.payload()
        try:
            if self.kind == "category":
                self.repository.update_category(item["id"], data["name"], data["color"])
            elif self.kind == "person":
                self.repository.update_person(item["id"], data["name"], data["notes"], data["color"])
            else:
                self.repository.update_tag(item["id"], data["name"], data["color"])
        except (sqlite3.IntegrityError, ValueError) as exc:
            show_warning(self, "ویرایش انجام نشد", self._friendly_error(exc))
            return
        self.refresh()
        self.changed.emit()

    def delete_selected(self) -> None:
        item = self.selected_item()
        if not item:
            show_info(self, "انتخاب مورد", "ابتدا یک مورد را از فهرست انتخاب کن.")
            return
        type_label = "دسته‌بندی" if self.kind == "category" else ("شخص" if self.kind == "person" else "برچسب")
        if not confirm(
            self, f"حذف {type_label}",
            f"«{item['name']}» حذف شود؟\n\nرویدادهای موجود باقی می‌مانند؛ فقط ارتباط آن‌ها با این {type_label} پاک می‌شود.",
        ):
            return
        if self.kind == "category":
            self.repository.delete_category(item["id"])
        elif self.kind == "person":
            self.repository.delete_person(item["id"])
        else:
            self.repository.delete_tag(item["id"])
        self.refresh()
        self.changed.emit()

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc)
        if isinstance(exc, sqlite3.IntegrityError):
            return "نام تکراری است. نام دیگری انتخاب کن."
        return message


class ManagementPage(QWidget):
    changed = Signal()

    def __init__(self, repository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 25, 28, 22)
        outer.setSpacing(17)

        header = QVBoxLayout()
        eyebrow = QLabel("YOUR ORGANIZER")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("مدیریت دسته‌بندی‌ها، اشخاص و برچسب‌ها")
        title.setObjectName("pageTitle")
        subtitle = QLabel("اطلاعات پایه را یک‌بار تعریف کن و در سراسر ژورنال دوباره استفاده کن.")
        subtitle.setObjectName("muted")
        header.addWidget(eyebrow)
        header.addWidget(title)
        header.addWidget(subtitle)
        outer.addLayout(header)

        card = QFrame()
        card.setObjectName("surfaceCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        self.tabs = QTabWidget()
        self.category_panel = ReferencePanel(repository, "category")
        self.people_panel = ReferencePanel(repository, "person")
        self.tags_panel = ReferencePanel(repository, "tag")
        self.tabs.addTab(self.category_panel, "دسته‌بندی‌ها")
        self.tabs.addTab(self.people_panel, "اشخاص")
        self.tabs.addTab(self.tags_panel, "برچسب‌ها")
        card_layout.addWidget(self.tabs)
        outer.addWidget(card, 1)

        self.category_panel.changed.connect(self.changed.emit)
        self.people_panel.changed.connect(self.changed.emit)
        self.tags_panel.changed.connect(self.changed.emit)

    def refresh(self) -> None:
        self.category_panel.refresh()
        self.people_panel.refresh()
        self.tags_panel.refresh()
