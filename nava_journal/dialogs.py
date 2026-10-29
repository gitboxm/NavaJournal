from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QBoxLayout, QLabel, QInputDialog,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QGridLayout, QWidget, QScrollArea, QSizePolicy,
)

from .jalali import MONTHS, current_jalali, format_jalali, iso_from_jalali, jalali_parts_from_iso
from .theme import contrast_foreground, theme_colors
from .rtl import apply_rtl, display_digits, show_warning
from .ui_components import AutoGrowTextEdit, FlowLayout, NoWheelComboBox, fit_combo_to_contents


class _AttachmentNoteLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class JalaliDatePicker(QWidget):
    """A three-combo Jalali date picker; values are stored as Gregorian ISO dates."""

    date_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None, initial_iso: str | None = None) -> None:
        super().__init__(parent)
        today = current_jalali()
        start_year = max(1200, today.year - 30)
        end_year = min(1600, today.year + 10)
        self.year = NoWheelComboBox()
        self.month = NoWheelComboBox()
        self.day = NoWheelComboBox()
        self.year.setObjectName("dateYear")
        self.month.setObjectName("dateMonth")
        self.day.setObjectName("dateDay")
        for year in range(start_year, end_year + 1):
            # Display only the two-digit year; keep the full Jalali year in itemData.
            self.year.addItem(display_digits(f"{year % 100:02d}"), year)
        for index, month_name in enumerate(MONTHS, start=1):
            self.month.addItem(month_name, index)
        # Date controls intentionally use physical LTR grid order: year at left,
        # month center, day at right. The rest of the dialog remains RTL.
        self.setProperty("navaPreserveLayoutDirection", True)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        for combo in (self.year, self.month, self.day):
            combo.setProperty("navaPreserveLayoutDirection", True)
            combo.setProperty("navaPreserveAlignment", True)
            combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(5)
        year_label, month_label, day_label = QLabel("سال"), QLabel("ماه"), QLabel("روز")
        for label in (year_label, month_label, day_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("navaPreserveAlignment", True)
            label.setObjectName("dateFieldLabel")
        for column in range(3):
            layout.setColumnStretch(column, 1)
        layout.addWidget(year_label, 0, 0)
        layout.addWidget(month_label, 0, 1)
        layout.addWidget(day_label, 0, 2)
        layout.addWidget(self.year, 1, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.month, 1, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.day, 1, 2, Qt.AlignmentFlag.AlignCenter)
        self.preview = QLabel("")
        self.preview.setObjectName("datePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.preview, 2, 0, 1, 3)
        self.year.setToolTip("سال با نمایش دورقمی؛ سال کامل در پایگاه داده ذخیره می‌شود.")
        for combo, minimum_width, maximum_width in (
            (self.year, 78, 94), (self.month, 108, 142), (self.day, 70, 88)
        ):
            combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            fit_combo_to_contents(combo, minimum_width=minimum_width, maximum_width=maximum_width)
            for item_index in range(combo.count()):
                combo.setItemData(item_index, int(Qt.AlignmentFlag.AlignCenter), Qt.ItemDataRole.TextAlignmentRole)
        self.year.currentIndexChanged.connect(self._rebuild_days)
        self.month.currentIndexChanged.connect(self._rebuild_days)
        self.day.currentIndexChanged.connect(self._emit_date)
        self.month.currentIndexChanged.connect(self._emit_date)
        self.year.currentIndexChanged.connect(self._emit_date)
        self.set_iso(initial_iso or today.to_gregorian().isoformat())

    def _rebuild_days(self, *_: object) -> None:
        year = self.year.currentData()
        month = self.month.currentData()
        if year is None or month is None:
            return
        try:
            old_day = int(self.day.currentData() or 1)
        except (TypeError, ValueError):
            old_day = 1
        max_day = 31 if month <= 6 else 30
        if month == 12:
            try:
                iso_from_jalali(int(year), 12, 30)
                max_day = 30
            except ValueError:
                max_day = 29
        self.day.blockSignals(True)
        self.day.clear()
        for value in range(1, max_day + 1):
            self.day.addItem(display_digits(value), value)
            self.day.setItemData(self.day.count() - 1, int(Qt.AlignmentFlag.AlignCenter), Qt.ItemDataRole.TextAlignmentRole)
        self.day.setCurrentIndex(min(old_day, max_day) - 1)
        self.day.blockSignals(False)

    def _emit_date(self, *_: object) -> None:
        try:
            value = self.to_iso()
        except (ValueError, TypeError):
            return
        self.date_changed.emit(value)
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            self.preview.setText(f"نمایش در ژورنال:  {display_digits(format_jalali(self.to_iso()))}")
        except (ValueError, TypeError):
            self.preview.setText("")

    def set_iso(self, iso_date: str) -> None:
        year, month, day = jalali_parts_from_iso(iso_date)
        for combo, value in ((self.year, year), (self.month, month)):
            idx = combo.findData(value)
            if idx < 0:
                combo.addItem(display_digits(f"{value % 100:02d}" if combo is self.year else value), value)
                combo.setItemData(combo.count() - 1, int(Qt.AlignmentFlag.AlignCenter), Qt.ItemDataRole.TextAlignmentRole)
                idx = combo.findData(value)
            combo.setCurrentIndex(idx)
        self._rebuild_days()
        day_index = self.day.findData(day)
        if day_index >= 0:
            self.day.setCurrentIndex(day_index)

    def to_iso(self) -> str:
        year = int(self.year.currentData())
        month = int(self.month.currentData())
        day = int(self.day.currentData())
        return iso_from_jalali(year, month, day)

    def jalali_text(self) -> str:
        """Compact display string only; does not lose the selected full year."""
        try:
            year = int(self.year.currentData())
            month = int(self.month.currentData())
            day = int(self.day.currentData())
            return f"{year % 100:02d}.{month:02d}.{day:02d}"
        except (TypeError, ValueError):
            return ""

    def jalali_storage_text(self) -> str:
        """Four-digit Jalali date for the database, never for the journal display."""
        try:
            year = int(self.year.currentData())
            month = int(self.month.currentData())
            day = int(self.day.currentData())
            return f"{year:04d}-{month:02d}-{day:02d}"
        except (TypeError, ValueError):
            return ""


class EntryDialog(QDialog):
    references_changed = Signal()

    def __init__(
        self,
        categories: list[dict],
        people: list[dict] | None = None,
        tags: list[dict] | None = None,
        repository=None,
        entry: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry or {}
        self.repository = repository
        self._tags = list(tags or [])
        self._attachments: list[tuple[str, str, str]] = []
        self.setWindowTitle("ویرایش رویداد" if entry else "ثبت رویداد تازه")
        # Give the entry editor 5% more width without changing its vertical rhythm.
        self.setMinimumSize(756, 620)
        self.resize(840, 700)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("entryScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content_widget = QWidget()
        content_widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        form_layout = QVBoxLayout(content_widget)
        form_layout.setContentsMargins(10, 10, 10, 12)
        form_layout.setSpacing(14)
        self.scroll_area.setWidget(content_widget)
        outer.addWidget(self.scroll_area, 1)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        eyebrow = QLabel("JOURNAL ENTRY")
        eyebrow.setObjectName("eyebrow")
        heading = QLabel("ویرایش رویداد" if entry else "یک رویداد تازه ثبت کن")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("تاریخ شمسی، یادداشت و فایل‌های مرتبط را یک‌جا نگه دار.")
        subtitle.setObjectName("muted")
        title_box.addWidget(eyebrow)
        title_box.addWidget(heading)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        form_layout.addLayout(header)

        title_label = QLabel("عنوان رویداد  *")
        self.title_edit = QLineEdit(str(self.entry.get("title", "")))
        self.title_edit.setPlaceholderText("مثلاً: پیگیری پرونده بانکی، تعمیر لپ‌تاپ...")
        self.title_edit.setClearButtonEnabled(True)
        self.title_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.addWidget(title_label)
        form_layout.addWidget(self.title_edit)

        date_box = QFrame()
        date_box.setObjectName("dateCard")
        date_layout = QVBoxLayout(date_box)
        date_layout.setContentsMargins(16, 13, 16, 12)
        date_layout.setSpacing(8)
        date_heading = QLabel("تاریخ رویداد")
        date_heading.setObjectName("sectionTitle")
        date_layout.addWidget(date_heading)
        self.date_picker = JalaliDatePicker(initial_iso=self.entry.get("event_date"))
        date_layout.addWidget(self.date_picker)
        form_layout.addWidget(date_box)

        # Four metadata fields share one responsive row to restore the compact, aligned form.
        fields_row = QHBoxLayout()
        fields_row.setDirection(QBoxLayout.Direction.RightToLeft)
        fields_row.setSpacing(10)
        field_specs = []

        category_box = QVBoxLayout()
        category_box.setSpacing(5)
        category_label = QLabel("دسته‌بندی")
        category_label.setObjectName("fieldLabel")
        category_box.addWidget(category_label)
        self.category_combo = NoWheelComboBox()
        self.category_combo.setMinimumHeight(38)
        self.category_combo.addItem("بدون دسته‌بندی", None)
        for category in categories:
            self.category_combo.addItem(category["name"], category["id"])
        category_id = self.entry.get("category_id")
        category_index = self.category_combo.findData(category_id)
        if category_index >= 0:
            self.category_combo.setCurrentIndex(category_index)
        field_specs.append((category_box, self.category_combo))

        person_box = QVBoxLayout()
        person_box.setSpacing(5)
        person_label = QLabel("شخص مرتبط · اختیاری")
        person_label.setObjectName("fieldLabel")
        person_box.addWidget(person_label)
        self.person_combo = NoWheelComboBox()
        self.person_combo.setMinimumHeight(38)
        self.person_combo.addItem("بدون شخص", None)
        for person in (people or []):
            self.person_combo.addItem(person["name"], person["id"])
        person_id = self.entry.get("person_id")
        person_index = self.person_combo.findData(person_id)
        if person_index >= 0:
            self.person_combo.setCurrentIndex(person_index)
        field_specs.append((person_box, self.person_combo))

        importance_box = QVBoxLayout()
        importance_box.setSpacing(5)
        importance_label = QLabel("اهمیت رویداد")
        importance_label.setObjectName("fieldLabel")
        importance_box.addWidget(importance_label)
        self.importance_combo = NoWheelComboBox()
        self.importance_combo.setMinimumHeight(38)
        for label, value in (("عادی", "normal"), ("مهم", "important"), ("فوری / بحرانی", "critical")):
            self.importance_combo.addItem(label, value)
        importance_index = self.importance_combo.findData(self.entry.get("importance", "normal"))
        self.importance_combo.setCurrentIndex(importance_index if importance_index >= 0 else 0)
        field_specs.append((importance_box, self.importance_combo))

        followup_box = QVBoxLayout()
        followup_box.setSpacing(5)
        followup_label = QLabel("وضعیت پیگیری")
        followup_label.setObjectName("fieldLabel")
        followup_box.addWidget(followup_label)
        self.follow_up_combo = NoWheelComboBox()
        self.follow_up_combo.setMinimumHeight(38)
        for label, value in (("بدون پیگیری", "none"), ("نیازمند پیگیری", "pending"), ("در حال انجام", "in_progress"), ("انجام شده", "done")):
            self.follow_up_combo.addItem(label, value)
        followup_index = self.follow_up_combo.findData(self.entry.get("follow_up_status", "none"))
        self.follow_up_combo.setCurrentIndex(followup_index if followup_index >= 0 else 0)
        field_specs.append((followup_box, self.follow_up_combo))

        for field_layout, combo in field_specs:
            combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(7)
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            field_layout.addWidget(combo)
            holder = QWidget()
            holder.setLayout(field_layout)
            holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            fields_row.addWidget(holder, 1)
        form_layout.addLayout(fields_row)

        tag_box = QFrame()
        tag_box.setObjectName("dateCard")
        tag_layout = QVBoxLayout(tag_box)
        tag_layout.setContentsMargins(14, 12, 14, 12)
        tag_layout.setSpacing(10)
        tag_header = QHBoxLayout()
        tag_title = QLabel("برچسب‌ها  ·  اختیاری")
        tag_title.setObjectName("sectionTitle")
        tag_header.addWidget(tag_title)
        tag_header.addStretch(1)
        self.tag_count_label = QLabel("۰ برچسب")
        self.tag_count_label.setObjectName("muted")
        tag_header.addWidget(self.tag_count_label)
        tag_layout.addLayout(tag_header)
        tag_help = QLabel("برچسب‌ها به شکل چیپ‌های تعاملی نمایش داده می‌شوند؛ چند مورد را انتخاب کن یا یک برچسب تازه بساز.")
        tag_help.setObjectName("muted")
        tag_help.setWordWrap(True)
        tag_layout.addWidget(tag_help)
        self.tag_chip_container = QWidget()
        self.tag_chip_container.setObjectName("tagChipPanel")
        self.tag_chip_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.tag_chip_layout = FlowLayout(self.tag_chip_container, margin=2, h_spacing=8, v_spacing=8)
        tag_layout.addWidget(self.tag_chip_container)
        add_tag_row = QHBoxLayout()
        self.new_tag_edit = QLineEdit()
        self.new_tag_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.new_tag_edit.setPlaceholderText("نام برچسب جدید...")
        self.new_tag_edit.setClearButtonEnabled(True)
        self.add_tag_button = QPushButton("＋ ساخت و افزودن")
        self.add_tag_button.setProperty("primary", True)
        add_tag_row.addWidget(self.new_tag_edit, 1)
        add_tag_row.addWidget(self.add_tag_button)
        tag_layout.addLayout(add_tag_row)
        form_layout.addWidget(tag_box)
        self._tag_buttons: dict[int, QPushButton] = {}
        self._refresh_tag_items(set(int(value) for value in self.entry.get("tag_ids", [])))
        self.add_tag_button.clicked.connect(self._add_tag_from_form)
        self.new_tag_edit.returnPressed.connect(self._add_tag_from_form)

        body_header = QHBoxLayout()
        body_title = QLabel("یادداشت و توضیحات")
        body_title.setObjectName("sectionTitle")
        body_header.addWidget(body_title)
        body_header.addStretch(1)
        self.note_toggle_button = QPushButton("− پنهان‌کردن یادداشت" if str(self.entry.get("body", "")).strip() else "＋ افزودن یادداشت")
        self.note_toggle_button.setProperty("compact", True)
        self.note_toggle_button.setCheckable(True)
        self.note_toggle_button.setChecked(bool(str(self.entry.get("body", "")).strip()))
        body_header.addWidget(self.note_toggle_button)
        form_layout.addLayout(body_header)
        self.body_edit = AutoGrowTextEdit()
        self.body_edit.setObjectName("autoGrowNotes")
        self.body_edit.setPlaceholderText("جزئیات، تصمیم‌ها، شماره پیگیری و نکته‌های مهم را بنویس؛ کادر با متن بزرگ می‌شود...")
        self.body_edit.setPlainText(str(self.entry.get("body", "")))
        self.body_edit.setVisible(bool(str(self.entry.get("body", "")).strip()))
        form_layout.addWidget(self.body_edit)
        self.note_toggle_button.toggled.connect(self._toggle_notes)

        attachment_header = QHBoxLayout()
        attachment_title = QLabel("فایل‌ها و پوشه‌های مرتبط")
        attachment_title.setObjectName("sectionTitle")
        attachment_header.addWidget(attachment_title)
        attachment_header.addStretch(1)
        self.attachment_count = QLabel("۰ مورد")
        self.attachment_count.setObjectName("muted")
        attachment_header.addWidget(self.attachment_count)
        form_layout.addLayout(attachment_header)
        attachment_hint = QLabel("هر فایل یا پوشه در یک کارت مستقل نمایش داده می‌شود. با افزودن موارد بیشتر، فهرست به‌صورت عمودی رشد می‌کند؛ اسکرول داخلی ندارد.")
        attachment_hint.setObjectName("muted")
        attachment_hint.setWordWrap(True)
        form_layout.addWidget(attachment_hint)

        self.attachment_cards_host = QWidget()
        self.attachment_cards_host.setObjectName("attachmentCardsHost")
        self.attachment_cards_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.attachment_cards_layout = QVBoxLayout(self.attachment_cards_host)
        self.attachment_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_cards_layout.setSpacing(8)
        form_layout.addWidget(self.attachment_cards_host)
        attachment_buttons = QHBoxLayout()
        self.add_file_button = QPushButton("＋ افزودن فایل‌ها")
        self.add_file_button.setProperty("primary", True)
        self.add_folder_button = QPushButton("▣ افزودن پوشه")
        attachment_buttons.addWidget(self.add_file_button)
        attachment_buttons.addWidget(self.add_folder_button)
        attachment_buttons.addStretch(1)
        form_layout.addLayout(attachment_buttons)

        self.favorite_check = QCheckBox("افزودن به علاقه‌مندی‌ها")
        self.favorite_check.setChecked(bool(self.entry.get("is_favorite", 0)))
        form_layout.addWidget(self.favorite_check)

        footer = QHBoxLayout()
        # LTR item order: stretch occupies the left; action buttons sit flush right.
        footer.setDirection(QBoxLayout.Direction.LeftToRight)
        self.save_button = QPushButton("ذخیره رویداد")
        self.save_button.setProperty("primary", True)
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton("انصراف")
        footer.addStretch(1)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        outer.addLayout(footer)

        self.add_file_button.clicked.connect(self.add_files)
        self.add_folder_button.clicked.connect(self.add_folder)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._validate_and_accept)

        for attachment in self.entry.get("attachments", []):
            self._append_attachment(
                attachment["path"], attachment.get("kind", "file"),
                str(attachment.get("notes") or ""), rerender=False,
            )
        self._render_attachment_cards()
        self._update_attachment_count()
        apply_rtl(self)
        self.title_edit.setFocus()

    def _refresh_tag_items(self, selected_ids: set[int] | None = None) -> None:
        selected_ids = selected_ids or set()
        if self.repository is not None:
            self._tags = self.repository.tags()
        self._tag_buttons.clear()
        while self.tag_chip_layout.count():
            item = self.tag_chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for tag in self._tags:
            tag_id = int(tag["id"])
            color = str(tag.get("color") or "#38BDF8")
            button = QPushButton(f"#  {tag['name']}")
            button.setObjectName("tagChip")
            button.setProperty("chip", True)
            button.setCheckable(True)
            button.setChecked(tag_id in selected_ids)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip("برای انتخاب یا برداشتن این برچسب کلیک کن.")
            # Color is taken from the user's local tag record. QColor validates it first.
            qcolor = QColor(color)
            if not qcolor.isValid():
                color = "#38BDF8"
            button.setStyleSheet(
                f"QPushButton{{border:1px solid {color}; border-radius:14px; padding:7px 12px; "
                f"background:transparent; color:{color}; min-height:0;}} "
                f"QPushButton:checked{{background:{color}; color:{contrast_foreground(color)}; font-weight:700;}} "
                f"QPushButton:hover{{border-width:2px;}}"
            )
            button.toggled.connect(self._update_tag_count)
            self._tag_buttons[tag_id] = button
            self.tag_chip_layout.addWidget(button)
        self.tag_chip_container.updateGeometry()
        self._update_tag_count()

    def _selected_tag_ids(self) -> list[int]:
        return [tag_id for tag_id, button in self._tag_buttons.items() if button.isChecked()]

    def _update_tag_count(self, *_: object) -> None:
        count = len(self._selected_tag_ids()) if hasattr(self, "_tag_buttons") else 0
        self.tag_count_label.setText(f"{display_digits(count)} برچسب انتخاب‌شده")

    def _add_tag_from_form(self) -> None:
        name = self.new_tag_edit.text().strip()
        if not name:
            return
        if self.repository is None:
            show_warning(self, "امکان ساخت برچسب نیست", "برای ساخت برچسب تازه، مخزن داده به فرم متصل نشده است.")
            return
        try:
            tag_id = self.repository.add_tag(name)
        except Exception as exc:
            show_warning(self, "ساخت برچسب انجام نشد", str(exc))
            return
        self.references_changed.emit()
        selected = set(self._selected_tag_ids())
        selected.add(int(tag_id))
        self._refresh_tag_items(selected)
        self.new_tag_edit.clear()

    def _toggle_notes(self, visible: bool) -> None:
        self.body_edit.setVisible(visible)
        self.note_toggle_button.setText("− پنهان‌کردن یادداشت" if visible else "＋ افزودن یادداشت")
        if visible:
            self.body_edit.setFocus()
            self.body_edit._sync_height()
        self.adjustSize()

    def _append_attachment(
        self, path: str, kind: str, note: str = "", rerender: bool = True
    ) -> None:
        normalized = str(Path(path))
        existing_index = next((i for i, item in enumerate(self._attachments) if item[0] == normalized), None)
        if existing_index is not None:
            old_path, old_kind, old_note = self._attachments[existing_index]
            self._attachments[existing_index] = (old_path, kind or old_kind, note if note else old_note)
            return
        self._attachments.append((normalized, kind, note))
        if rerender and hasattr(self, "attachment_cards_layout"):
            self._render_attachment_cards()
            self._grow_for_attachments()
        self._update_attachment_count()

    def _render_attachment_cards(self) -> None:
        while self.attachment_cards_layout.count():
            item = self.attachment_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for path, kind, note in self._attachments:
            self._add_attachment_card(path, kind, note)
        self.attachment_cards_host.updateGeometry()

    def _add_attachment_card(self, path: str, kind: str, note: str = "") -> None:
        card = QFrame()
        card.setObjectName("attachmentItem")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(10)
        icon = QLabel("▣" if kind == "folder" else "↗")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setProperty("navaPreserveCenter", True)
        icon.setFixedSize(42, 42)
        palette = theme_colors()
        icon.setStyleSheet(
            f"background:{palette['surface3']}; color:{palette['accent']}; border:1px solid {palette['border']}; "
            "border-radius:13px; font-size:17pt; font-weight:800;"
        )
        card_layout.addWidget(icon)
        info = QVBoxLayout()
        info.setSpacing(4)
        name = QLabel(Path(path).name or path)
        name.setObjectName("recentTitle")
        name.setWordWrap(True)
        name.setToolTip(path)
        location = QLabel(path)
        location.setObjectName("muted")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.setToolTip(path)
        info.addWidget(name)
        info.addWidget(location)
        note_label = _AttachmentNoteLabel()
        note_label.setObjectName("attachmentNote")
        note_label.setWordWrap(True)
        note_label.setText(f"یادداشت پیوست: {note}" if note.strip() else "＋  افزودن یادداشت برای این فایل یا پوشه · دوبار کلیک")
        note_label.setToolTip("دوبار کلیک برای ویرایش یا حذف یادداشت این پیوست")
        note_label.double_clicked.connect(lambda *_args, selected_path=path: self._edit_attachment_note(selected_path))
        info.addWidget(note_label)
        card_layout.addLayout(info, 1)
        kind_label = QLabel("پوشه" if kind == "folder" else "فایل")
        kind_label.setObjectName("pillLabel")
        card_layout.addWidget(kind_label, 0, Qt.AlignmentFlag.AlignVCenter)
        open_button = QPushButton("بازکردن")
        open_button.setProperty("compact", True)
        open_button.clicked.connect(lambda _checked=False, selected_path=path: self._open_attachment_path(selected_path))
        remove_button = QPushButton("حذف")
        remove_button.setProperty("compact", True)
        remove_button.setProperty("danger", True)
        remove_button.clicked.connect(lambda _checked=False, selected_path=path: self._remove_attachment_path(selected_path))
        card_layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.attachment_cards_layout.addWidget(card)

    def _edit_attachment_note(self, path: str) -> None:
        record = next((item for item in self._attachments if item[0] == path), None)
        if record is None:
            return
        old_note = record[2]
        dialog = QDialog(self)
        dialog.setWindowTitle("یادداشت پیوست")
        dialog.setMinimumWidth(460)
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        heading = QLabel(Path(path).name or path)
        heading.setObjectName("sectionTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        editor = AutoGrowTextEdit(min_height=64)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        editor.setPlainText(old_note)
        editor.setPlaceholderText("یادداشتی درباره همین فایل یا پوشه بنویس...")
        layout.addWidget(editor)
        buttons = QHBoxLayout()
        buttons.setDirection(QBoxLayout.Direction.RightToLeft)
        save_button = QPushButton("ذخیره یادداشت")
        save_button.setProperty("primary", True)
        delete_button = QPushButton("حذف یادداشت")
        delete_button.setProperty("danger", True)
        delete_button.setVisible(bool(old_note.strip()))
        cancel_button = QPushButton("انصراف")
        buttons.addWidget(save_button)
        buttons.addWidget(delete_button)
        buttons.addWidget(cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        save_button.clicked.connect(lambda: dialog.done(1))
        delete_button.clicked.connect(lambda: dialog.done(2))
        cancel_button.clicked.connect(dialog.reject)
        apply_rtl(dialog)
        result = dialog.exec()
        if result == 1:
            new_note = editor.toPlainText().strip()
        elif result == 2:
            new_note = ""
        else:
            return
        self._attachments = [
            (item_path, item_kind, new_note if item_path == path else item_note)
            for item_path, item_kind, item_note in self._attachments
        ]
        self._render_attachment_cards()
        self._grow_for_attachments()

    def _update_attachment_count(self) -> None:
        self.attachment_count.setText(f"{display_digits(len(self._attachments))} مورد")

    def _grow_for_attachments(self) -> None:
        """Grow the dialog up to the available screen height; only the whole form may scroll."""
        try:
            screen = self.screen()
            if screen is None:
                return
            available = screen.availableGeometry()
            desired = min(available.height() - 70, max(self.height(), self.height() + 54))
            if desired > self.height():
                self.resize(min(max(self.width(), 840), available.width() - 50), desired)
        except RuntimeError:
            pass

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب فایل‌های مرتبط")
        for path in paths:
            self._append_attachment(path, "file")

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "انتخاب پوشه مرتبط")
        if path:
            self._append_attachment(path, "folder")

    def _remove_attachment_path(self, path: str) -> None:
        self._attachments = [item for item in self._attachments if item[0] != path]
        self._render_attachment_cards()
        self._update_attachment_count()

    def _open_attachment_path(self, path: str) -> None:
        if not Path(path).exists():
            show_warning(self, "مسیر در دسترس نیست", "این فایل یا پوشه پیدا نشد. ممکن است جابه‌جا یا حذف شده باشد.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _validate_and_accept(self) -> None:
        if not self.title_edit.text().strip():
            show_warning(self, "عنوان لازم است", "برای ثبت رویداد، عنوانی وارد کن.")
            self.title_edit.setFocus()
            return
        try:
            self.date_picker.to_iso()
        except (TypeError, ValueError) as exc:
            show_warning(self, "تاریخ نامعتبر", f"تاریخ شمسی انتخاب‌شده معتبر نیست.\n{exc}")
            return
        self.accept()

    def payload(self) -> dict:
        return {
            "id": self.entry.get("id"),
            "title": self.title_edit.text().strip(),
            "body": self.body_edit.toPlainText().strip(),
            "event_date": self.date_picker.to_iso(),
            "event_jalali_date": self.date_picker.jalali_storage_text(),
            "category_id": self.category_combo.currentData(),
            "person_id": self.person_combo.currentData(),
            "importance": self.importance_combo.currentData(),
            "follow_up_status": self.follow_up_combo.currentData(),
            "tag_ids": self._selected_tag_ids(),
            "is_favorite": self.favorite_check.isChecked(),
        }

    def attachment_paths(self) -> list[tuple[str, str, str]]:
        return list(self._attachments)
