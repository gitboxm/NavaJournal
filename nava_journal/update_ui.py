from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from .rtl import apply_rtl


class UpdateSelectionDialog(QDialog):
    """Ask which coherent change groups should be included in this update."""

    def __init__(self, manifest: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manifest = manifest
        self.setWindowTitle("انتخاب تغییرات به‌روزرسانی")
        self.setModal(True)
        self.setMinimumSize(620, 510)
        self.resize(720, 620)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        heading = QLabel(f"قبل از نصب نسخه {manifest.get('version', '—')} تغییرات را انتخاب کن")
        heading.setObjectName("pageTitle")
        intro = QLabel(
            "هر گزینه یک مجموعه مستقل از فایل‌هاست. تیک هر مورد را برداری، فایل‌های همان مجموعه اعمال نمی‌شوند. "
            "تغییرات مرتبط در یک گروه قرار گرفته‌اند تا نیمه‌کاره نصب نشوند."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        outer.addWidget(heading)
        outer.addWidget(intro)

        self.select_all = QCheckBox("انتخاب همه تغییرات")
        self.select_all.setObjectName("updateSelectAll")
        self.select_all.setChecked(True)
        outer.addWidget(self.select_all)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.groups_host = QWidget()
        self.groups_host.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        groups_layout = QVBoxLayout(self.groups_host)
        groups_layout.setContentsMargins(2, 2, 7, 2)
        groups_layout.setSpacing(9)
        self.group_checks: dict[str, QCheckBox] = {}

        groups = manifest.get("change_groups") or []
        for group in groups:
            card = QFrame()
            card.setObjectName("settingsCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)
            check = QCheckBox(str(group.get("title") or group["id"]))
            check.setChecked(True)
            check.setProperty("changeGroupId", str(group["id"]))
            check.setStyleSheet("font-weight:750; font-size:10.5pt;")
            description = QLabel(str(group.get("description") or "توضیحی برای این مجموعه ثبت نشده است."))
            description.setObjectName("muted")
            description.setWordWrap(True)
            paths = group.get("files") or []
            files_label = QLabel(f"{len(paths)} فایل · " + "، ".join(str(PathName) for PathName in paths[:3]) + (" …" if len(paths) > 3 else ""))
            files_label.setObjectName("updateStatus")
            files_label.setWordWrap(True)
            card_layout.addWidget(check)
            card_layout.addWidget(description)
            card_layout.addWidget(files_label)
            groups_layout.addWidget(card)
            self.group_checks[str(group["id"])] = check
            check.toggled.connect(self._refresh_master)

        groups_layout.addStretch(1)
        scroll.setWidget(self.groups_host)
        outer.addWidget(scroll, 1)

        always = manifest.get("always_apply_files") or []
        if always:
            required_card = QFrame()
            required_card.setObjectName("surfaceCard")
            required_layout = QVBoxLayout(required_card)
            required_layout.setContentsMargins(12, 9, 12, 9)
            required_title = QLabel("فایل‌های پایه این انتشار")
            required_title.setStyleSheet("font-weight:750;")
            required_detail = QLabel(
                "این فایل‌ها چارچوب مشترک انتخابی‌بودن تغییرات و شماره نسخه را فراهم می‌کنند؛ مستقل از اینکه کدام قابلیت را تیک بزنی، همیشه اعمال می‌شوند: "
                + "، ".join(always)
            )
            required_detail.setObjectName("muted")
            required_detail.setWordWrap(True)
            required_layout.addWidget(required_title)
            required_layout.addWidget(required_detail)
            outer.addWidget(required_card)

        self.selection_summary = QLabel("")
        self.selection_summary.setObjectName("updateStatus")
        outer.addWidget(self.selection_summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("ادامه با موارد انتخاب‌شده")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("انصراف")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.select_all.clicked.connect(self._toggle_all)
        self._refresh_master()
        apply_rtl(self)

    def _toggle_all(self, checked: bool) -> None:
        for check in self.group_checks.values():
            check.blockSignals(True)
            check.setChecked(bool(checked))
            check.blockSignals(False)
        self._refresh_master()

    def _refresh_master(self, *_: object) -> None:
        total = len(self.group_checks)
        selected = sum(1 for check in self.group_checks.values() if check.isChecked())
        self.select_all.blockSignals(True)
        if total and selected == total:
            self.select_all.setCheckState(Qt.CheckState.Checked)
        elif selected == 0:
            self.select_all.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        self.select_all.blockSignals(False)
        self.selection_summary.setText(f"{selected} از {total} مجموعه انتخاب شده است.")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(selected > 0)

    def selected_group_ids(self) -> list[str]:
        return [group_id for group_id, check in self.group_checks.items() if check.isChecked()]


class UpdateProgressDialog(QDialog):
    """A compact timeline shown while the app stages a differential patch."""

    def __init__(self, target_version: str, file_count: int, parent: QWidget | None = None, operation: str = "update") -> None:
        super().__init__(parent)
        self.operation = operation
        is_rollback = operation == "rollback"
        self.setWindowTitle("بازگشت نسخه روزنگار" if is_rollback else "به‌روزرسانی روزنگار")
        self.setModal(False)
        self.setMinimumWidth(560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(14)
        title = QLabel(f"{'بازگردانی به نسخه' if is_rollback else 'آماده‌سازی نسخه'} {target_version}")
        title.setObjectName("pageTitle")
        subtitle_text = (
            f"فقط {file_count} فایل از نسخه قبلی بازیابی می‌شود؛ اطلاعات شخصی حفظ می‌شود مگر آنکه بازگردانی پایگاه داده را هم انتخاب کرده باشی."
            if is_rollback else
            f"فقط {file_count} فایل انتخاب‌شده جایگزین می‌شود؛ پایگاه داده و فایل‌های شخصی دست‌نخورده می‌مانند."
        )
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)
        self.timeline = QListWidget()
        self.timeline.setMinimumHeight(190)
        self.timeline.setObjectName("updateTimeline")
        if is_rollback:
            steps = (
                ("بررسی نسخه قبلی", "فایل‌های نسخه قبل از به‌روزرسانی از پشتیبان آماده می‌شوند."),
                ("پشتیبان ایمنی", "فایل‌ها و پایگاه داده فعلی برای بازیابی خطا محافظت می‌شوند."),
                ("بازگردانی فایل‌ها", "فقط فایل‌های تغییرکرده به حالت قبلی برمی‌گردند."),
                ("اجرای دوباره", "روزنگار با نسخه قبلی باز می‌شود."),
            )
        else:
            steps = (
                ("بررسی فایل ZIP", "فهرست فایل‌ها، نسخه پایه و هش هر فایل بررسی شده است."),
                ("پشتیبان پایگاه داده", "یک نسخه پشتیبان مستقل از SQLite پیش از تغییر ساخته می‌شود."),
                ("آماده‌سازی فایل‌های انتخاب‌شده", "فقط فایل‌های متعلق به گروه‌های انتخابی آماده می‌شوند."),
                ("اعمال و راه‌اندازی مجدد", "عامل مستقل بعد از خروج برنامه فایل‌ها را اعمال و روزنگار را دوباره اجرا می‌کند."),
            )
        for heading, detail in steps:
            item = QListWidgetItem(f"○  {heading}\n    {detail}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.timeline.addItem(item)
        outer.addWidget(self.timeline)
        self.progress = QProgressBar()
        self.progress.setRange(0, 4)
        self.progress.setValue(3)
        outer.addWidget(self.progress)
        self.status_label = QLabel("در حال آماده‌سازی عامل مستقل…")
        self.status_label.setObjectName("muted")
        outer.addWidget(self.status_label)
        apply_rtl(self)

    def mark_ready_to_close(self) -> None:
        if self.timeline.count() > 3:
            self.timeline.item(0).setText(self.timeline.item(0).text().replace("○", "✓", 1))
            self.timeline.item(1).setText(self.timeline.item(1).text().replace("○", "✓", 1))
            self.timeline.item(2).setText(self.timeline.item(2).text().replace("○", "✓", 1))
            self.timeline.item(3).setText(self.timeline.item(3).text().replace("○", "◉", 1))
        self.progress.setValue(4)
        self.status_label.setText("عامل مستقل آماده است. روزنگار بسته و پس از اتمام عملیات دوباره اجرا می‌شود.")
