from __future__ import annotations

from pathlib import Path
from datetime import date
from urllib.parse import urlencode
import json
import logging
from PySide6.QtCore import Qt, Signal, QSettings, QUrl, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPixmap, QDesktopServices, QPainter, QPainterPath
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QBoxLayout, QMenu,
    QApplication, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QHeaderView,
)

from .jalali import (
    current_jalali, format_jalali, format_jalali_full, format_timestamp, iso_from_jalali,
    jalali_iso_today, jalali_sort_key, to_en_digits, MONTHS,
)
from .update_manager import UpdateError, UpdateManager
from .auto_backup import preferred_backup_folder
from .rtl import CENTERED_ROLE, apply_rtl, display_digits, show_info, table_alignment_flags
from .version import APP_VERSION
from .theme import semantic_color, theme_colors, contrast_foreground
from .ui_components import ProgressRing, NoWheelComboBox, fit_combo_to_contents
from .daily_inspiration import (
    SOURCE_API_URL, SOURCE_URL, SOURCE_LABEL, offline_message, parse_api_bytes,
)


# Labels are stable; colors are resolved from the active shared theme palette.
IMPORTANCE_LABELS = {"normal": "عادی", "important": "مهم", "critical": "فوری / بحرانی"}
FOLLOW_UP_LABELS = {"none": "بدون پیگیری", "pending": "نیازمند پیگیری", "in_progress": "در حال انجام", "done": "انجام شده"}


def theme_importance_color(value: str) -> str:
    return semantic_color({"normal": "normal", "important": "important", "critical": "critical"}.get(value, "normal"))


def theme_follow_up_color(value: str) -> str:
    return semantic_color({"none": "followup_none", "pending": "followup_pending", "in_progress": "followup_in_progress", "done": "followup_done"}.get(value, "followup_none"))


def make_page_header(title: str, subtitle: str) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(5)
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    supporting = QLabel(subtitle)
    supporting.setObjectName("muted")
    layout.addWidget(heading)
    layout.addWidget(supporting)
    return layout


def surface_card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("surfaceCard")
    return frame


def _rgba(color: str, alpha: int) -> str:
    parsed = QColor(color)
    if not parsed.isValid():
        parsed = QColor("#8B7CF6")
    return f"rgba({parsed.red()},{parsed.green()},{parsed.blue()},{max(0, min(255, int(alpha)))})"


class _ElidedMetricLabel(QLabel):
    """One-line metric text that stays compact and exposes the full text by tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._render_elided()

    def _render_elided(self) -> None:
        available = max(8, self.contentsRect().width() - 4)
        shown = QFontMetrics(self.font()).elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, available
        )
        super().setText(shown)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._render_elided()


class MetricCard(QFrame):
    """Compact dashboard metric with the value at the physical right edge."""

    def __init__(self, icon: str, label: str, accent: str = "") -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.setMinimumHeight(94)
        self.setMaximumHeight(98)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        color = accent or "#9B8CFF"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(3)

        # Keep the icon at the left and the numeric value at the right, regardless
        # of the application's RTL setting. This also makes six columns fit.
        headline = QHBoxLayout()
        headline.setDirection(QBoxLayout.Direction.LeftToRight)
        headline.setContentsMargins(0, 0, 0, 0)
        headline.setSpacing(6)
        icon_frame = QFrame(self)
        self._icon_frame = icon_frame
        self._accent_color = color
        icon_frame.setFixedSize(30, 30)
        icon_frame.setStyleSheet(
            f"background:{_rgba(color, 34)}; border:1px solid {_rgba(color, 95)}; border-radius:10px;"
        )
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.icon_label = QLabel(icon)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setProperty("navaPreserveCenter", True)
        self.icon_label.setStyleSheet(
            f"color:{color}; font-size:14pt; font-weight:800; background:transparent;"
        )
        icon_layout.addWidget(self.icon_label)
        headline.addWidget(icon_frame, 0, Qt.AlignmentFlag.AlignVCenter)
        headline.addStretch(1)

        self.value_label = QLabel(display_digits("0"))
        self.value_label.setObjectName("metricValue")
        self.value_label.setProperty("navaPreserveAlignment", True)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setMinimumWidth(28)
        headline.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(headline)

        self.caption_label = _ElidedMetricLabel(label, self)
        self.caption_label.setObjectName("metricLabel")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.caption_label)

        self.detail_label = _ElidedMetricLabel("", self)
        self.detail_label.setObjectName("metricDetail")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.detail_label)

    def set_accent(self, color: str) -> None:
        self._accent_color = str(color)
        self._icon_frame.setStyleSheet(
            f"background:{_rgba(self._accent_color, 34)}; border:1px solid {_rgba(self._accent_color, 95)}; border-radius:10px;"
        )
        self.icon_label.setStyleSheet(
            f"color:{self._accent_color}; font-size:14pt; font-weight:800; background:transparent;"
        )

    def set_value(self, value: int) -> None:
        self.value_label.setText(display_digits(value))

    def set_detail(self, detail: str) -> None:
        self.detail_label.set_full_text(str(detail or ""))
        self.detail_label.setVisible(bool(detail))
        self.setToolTip(str(detail or self.caption_label.toolTip()))


class _ElidedRecentTitle(QLabel):
    """A single-line title that truncates cleanly instead of distorting the card."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = str(text or "بدون عنوان")
        self.setToolTip(self._full_text)
        self.setWordWrap(False)
        self.setMinimumWidth(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setProperty("navaPreserveLayoutDirection", True)
        self.setProperty("navaPreserveAlignment", True)
        self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(12, self.contentsRect().width() - 4)
        self.setText(QFontMetrics(self.font()).elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, width
        ))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._apply_elision()


def _set_row_to_physical_rtl(layout: QBoxLayout) -> None:
    """Lay out an RTL-reading row with deterministic physical positions.

    Qt can mirror a horizontal box layout when both the parent widget and its
    layout direction are RTL.  For these compact dashboard cards we instead
    make the layout physically LTR and reverse its items once, so reading from
    the right edge yields the original Persian order.  Widget stretch factors,
    vertical alignment and expanding spacers are preserved.
    """
    items = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        stretch = max(0, int(layout.stretch(index)))
        alignment = item.alignment()
        if widget is not None:
            items.append(("widget", widget, stretch, alignment))
        elif item.spacerItem() is not None:
            items.append(("stretch", None, max(1, stretch), alignment))
        elif item.layout() is not None:
            items.append(("layout", item.layout(), stretch, alignment))

    while layout.count():
        layout.takeAt(0)

    layout.setDirection(QBoxLayout.Direction.LeftToRight)
    for kind, value, stretch, alignment in reversed(items):
        if kind == "widget":
            layout.addWidget(value, stretch, alignment)
        elif kind == "stretch":
            layout.addStretch(stretch)
        elif kind == "layout":
            layout.addLayout(value, stretch)


class RecentEntryCard(QFrame):
    """Stable, always-visible two-row journal card without note previews."""
    opened = Signal(int)
    _palette = ("#9B8CFF", "#65B8F5", "#4ED8B2", "#F4C977", "#FF718B")

    def __init__(self, entry: dict, index: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry_id = int(entry["id"])
        active_palette = theme_colors()
        self._palette = (
            active_palette["accent"], active_palette["success"], active_palette["warning"],
            active_palette["danger"], active_palette["muted"],
        )
        self.setObjectName("recentEntryCard")
        # The card's physical layout is LTR; the row items are reversed once
        # below so Persian reading order is right-to-left without Qt mirroring.
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setProperty("navaPreserveLayoutDirection", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(90)
        self.setMaximumHeight(102)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        color = str(entry.get("category_color") or self._palette[index % len(self._palette)])
        parsed = QColor(color)
        if not parsed.isValid():
            color = self._palette[index % len(self._palette)]

        # Keep the accent rail physically at the left regardless of RTL settings.
        outer = QHBoxLayout(self)
        outer.setDirection(QBoxLayout.Direction.LeftToRight)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        rail = QFrame(self)
        rail.setObjectName("recentAccentRail")
        rail.setFixedWidth(4)
        rail.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {color},stop:1 {_rgba(color, 145)}); "
            "border-top-left-radius:15px; border-bottom-left-radius:15px; border:none;"
        )
        outer.addWidget(rail)

        body = QVBoxLayout()
        body.setContentsMargins(12, 7, 12, 7)
        body.setSpacing(4)
        outer.addLayout(body, 1)

        # Row 1: person first, then concise metadata. All of it is visible before hover.
        metadata = QHBoxLayout()
        metadata.setDirection(QBoxLayout.Direction.RightToLeft)
        self._nava_metadata_layout = metadata
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(6)

        person_name = str(entry.get("person_name") or "").strip()
        if person_name:
            person = QLabel(f"●  {person_name}")
            person.setObjectName("recentPerson")
            person.setMaximumWidth(160)
            person.setToolTip(f"شخص مرتبط: {person_name}")
            metadata.addWidget(person, 0, Qt.AlignmentFlag.AlignVCenter)

        category_name = str(entry.get("category_name") or "بدون دسته")
        category_color = str(entry.get("category_color") or color)
        cat_qcolor = QColor(category_color)
        if not cat_qcolor.isValid():
            category_color = color
        category = QLabel(category_name)
        category.setObjectName("recentCategoryPill")
        category.setMaximumWidth(130)
        category.setToolTip(f"دسته‌بندی: {category_name}")
        category.setStyleSheet(
            f"background:{_rgba(category_color, 24)}; color:{category_color}; "
            f"border:1px solid {_rgba(category_color, 90)}; border-radius:8px; padding:2px 7px; font-weight:650;"
        )
        metadata.addWidget(category, 0, Qt.AlignmentFlag.AlignVCenter)

        date_text = display_digits(format_jalali(entry["event_date"]))
        date_chip = QLabel(date_text)
        date_chip.setObjectName("recentDateChip")
        date_chip.setToolTip("تاریخ شمسی رویداد")
        date_chip.setStyleSheet(
            f"background:{_rgba(color, 22)}; color:{color}; border:1px solid {_rgba(color, 78)}; "
            "border-radius:8px; padding:2px 7px; font-weight:750;"
        )
        metadata.addWidget(date_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        importance = str(entry.get("importance") or "normal")
        if importance != "normal":
            importance_text = IMPORTANCE_LABELS.get(importance, importance)
            importance_chip_color = theme_importance_color(importance)
            importance_chip = QLabel(importance_text)
            importance_chip.setObjectName("recentMetaChip")
            importance_chip.setToolTip("اهمیت رویداد")
            importance_chip.setStyleSheet(
                f"background:{_rgba(importance_chip_color, 22)}; color:{importance_chip_color}; "
                f"border:1px solid {_rgba(importance_chip_color, 78)}; border-radius:8px; padding:2px 7px; font-weight:650;"
            )
            metadata.addWidget(importance_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        tag_count = int(entry.get("tag_count") or 0)
        if tag_count:
            tag_count_label = QLabel(f"# {display_digits(tag_count)}")
            tag_count_label.setObjectName("recentTagCount")
            tag_count_label.setToolTip("تعداد برچسب‌ها")
            metadata.addWidget(tag_count_label, 0, Qt.AlignmentFlag.AlignVCenter)

        if entry.get("is_favorite"):
            favorite = QLabel("★")
            favorite.setObjectName("recentFavorite")
            favorite.setStyleSheet(f"color:{semantic_color('favorite')}; font-size:12pt; font-weight:800;")
            favorite.setToolTip("رویداد مورد علاقه")
            metadata.addWidget(favorite, 0, Qt.AlignmentFlag.AlignVCenter)

        metadata.addStretch(1)
        open_button = QPushButton("↗")
        open_button.setProperty("compact", True)
        open_button.setFixedSize(27, 25)
        open_button.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        open_button.setProperty("navaPreserveLayoutDirection", True)
        open_button.setToolTip("بازکردن رویداد")
        open_button.clicked.connect(lambda _checked=False: self.opened.emit(self.entry_id))
        metadata.addWidget(open_button, 0, Qt.AlignmentFlag.AlignVCenter)
        _set_row_to_physical_rtl(metadata)
        body.addLayout(metadata)

        # Row 2: title plus small follow-up/tag/attachment badges; never show body text.
        details = QHBoxLayout()
        details.setDirection(QBoxLayout.Direction.RightToLeft)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)
        title_text = str(entry.get("title") or "بدون عنوان")
        title = _ElidedRecentTitle(title_text)
        title.setObjectName("recentTitle")
        title.setMinimumHeight(22)
        title.setMaximumHeight(24)
        details.addWidget(title, 1)

        follow_up = str(entry.get("follow_up_status") or "none")
        if follow_up != "none":
            follow_text = FOLLOW_UP_LABELS.get(follow_up, follow_up)
            follow_color = theme_follow_up_color(follow_up)
            follow_chip = QLabel(follow_text)
            follow_chip.setObjectName("recentMetaChip")
            follow_chip.setToolTip("وضعیت پیگیری")
            follow_chip.setStyleSheet(
                f"background:{_rgba(follow_color, 22)}; color:{follow_color}; "
                f"border:1px solid {_rgba(follow_color, 78)}; border-radius:8px; padding:2px 7px; font-size:8pt;"
            )
            details.addWidget(follow_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        raw_tags = [part.strip() for part in str(entry.get("tag_names") or "").split("،") if part.strip()]
        if raw_tags:
            shown_tags = "  ·  ".join(f"#{name}" for name in raw_tags[:2])
            if len(raw_tags) > 2:
                shown_tags += f"  +{display_digits(len(raw_tags) - 2)}"
            tags_label = QLabel(shown_tags)
            tags_label.setObjectName("recentTags")
            tags_label.setMaximumWidth(180)
            tags_label.setToolTip("برچسب‌ها: " + "، ".join(raw_tags))
            details.addWidget(tags_label, 0, Qt.AlignmentFlag.AlignVCenter)

        attachment_count = int(entry.get("attachment_count") or 0)
        attachment_label = QLabel(f"↗ {display_digits(attachment_count)}")
        attachment_label.setObjectName("recentAttachmentCount")
        attachment_label.setToolTip("فایل‌ها و پوشه‌های مرتبط")
        details.addWidget(attachment_label, 0, Qt.AlignmentFlag.AlignVCenter)
        _set_row_to_physical_rtl(details)
        body.addLayout(details)
        self._nava_details_layout = details
        apply_rtl(self)
        self.enforce_right_alignment()

    def enforce_right_alignment(self) -> None:
        """Keep physical card rows stable while right-aligning Persian text."""
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setProperty("navaPreserveLayoutDirection", True)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for layout_name in ("_nava_metadata_layout", "_nava_details_layout"):
            layout = getattr(self, layout_name, None)
            if layout is not None:
                # The layout is physically LTR and was reversed exactly once at
                # construction. Keep that order stable after any global RTL pass.
                layout.setDirection(QBoxLayout.Direction.LeftToRight)
                for index in range(layout.count()):
                    item = layout.itemAt(index)
                    widget = item.widget() if item is not None else None
                    if isinstance(widget, QLabel):
                        widget.setAlignment(right)
        for widget in self.findChildren(QLabel):
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            widget.setProperty("navaPreserveLayoutDirection", True)
            widget.setProperty("navaPreserveAlignment", True)
            widget.setAlignment(right)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.opened.emit(self.entry_id)
        super().mouseDoubleClickEvent(event)


class DashboardPage(QWidget):
    new_requested = Signal()
    open_requested = Signal(int)
    view_all_requested = Signal()
    memories_requested = Signal()

    def __init__(self, repository, settings=None) -> None:
        super().__init__()
        self.repository = repository
        self.settings = settings or QSettings()
        self._quote_reply = None
        self._quote_day = date.today().isoformat()
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("dashboardScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 25, 28, 28)
        outer.setSpacing(19)
        self.scroll_area.setWidget(content)
        wrapper.addWidget(self.scroll_area)

        # A dedicated LTR host locks physical placement regardless of the saved
        # RTL/LTR preference. Local data stays on the far left; the greeting is
        # always on the far right. Text alignment is configured independently.
        top_host = QFrame()
        top_host.setObjectName("dashboardTopRow")
        top_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        top_host.setProperty("navaPreserveLayoutDirection", True)
        # Use a physical LTR grid: column 0 is always the left local-data card,
        # column 1 is the greeting area on the right. This avoids relying on
        # QHBoxLayout's mirroring behavior under an RTL parent.
        top = QGridLayout(top_host)
        top.setContentsMargins(22, 20, 22, 20)
        top.setHorizontalSpacing(22)
        top.setVerticalSpacing(0)
        top.setColumnStretch(0, 0)
        top.setColumnStretch(1, 1)
        self._nava_dashboard_top_host = top_host
        self._nava_dashboard_top_layout = top
        greeting_host = QWidget()
        greeting_host.setObjectName("dashboardGreeting")
        greeting_host.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        greeting_host.setProperty("navaPreserveLayoutDirection", True)
        greeting_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        greeting = QVBoxLayout(greeting_host)
        greeting.setContentsMargins(0, 0, 0, 0)
        greeting.setSpacing(6)
        content.setObjectName("dashboardCanvas")
        eyebrow = QLabel("حافظهٔ شخصی تو  ·  NAVA JOURNAL")
        eyebrow.setObjectName("eyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        eyebrow.setProperty("navaPreserveAlignment", True)
        title = QLabel("به روزنگار خوش آمدی")
        title.setObjectName("heroTitle")
        # This heading is a fixed RTL title; don't let the user's global text
        # alignment preference move the text to the opposite edge of its label.
        title.setProperty("navaPreserveAlignment", True)
        title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.today_label = QLabel("")
        self.today_label.setObjectName("dateBadge")
        self.today_label.setProperty("navaPreserveAlignment", True)
        self.today_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_label.setMinimumHeight(30)
        # Use an LTR physical row and explicit insertion order to avoid Qt's
        # RTL mirroring: stretch on the left, date beside the title, title at
        # the right edge. This is independent from the global text direction.
        title_row_host = QWidget()
        title_row_host.setObjectName("dashboardWelcomeTitleRow")
        title_row_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        title_row_host.setProperty("navaPreserveLayoutDirection", True)
        title_row_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_row = QGridLayout(title_row_host)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setHorizontalSpacing(12)
        title_row.setVerticalSpacing(0)
        title_row.setColumnStretch(0, 1)
        title_row.setColumnStretch(1, 0)
        title_row.setColumnStretch(2, 0)
        # Column order is physical LTR: empty flexible space, date, welcome title.
        title_row.addWidget(self.today_label, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(title, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.today_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        subtitle = QLabel("رویدادها، یادداشت‌ها و فایل‌های مهمت؛ در یک فضای آرام و مرتب.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(False)
        # The subtitle should use the full width under the heading. Right-align
        # its text inside the wide label rather than shrinking the label to its
        # sizeHint and letting the text wrap onto a second line.
        subtitle.setMinimumWidth(0)
        # Keep this label at its natural single-line width and physically anchor
        # the widget at the RIGHT edge of a dedicated LTR grid. Text alignment
        # alone was not enough because the global RTL pass could alter how the
        # expanding label was positioned inside its row.
        subtitle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        subtitle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        subtitle.setProperty("navaPreserveAlignment", True)
        subtitle.setProperty("navaPreserveLayoutDirection", True)
        subtitle_row_host = QWidget(greeting_host)
        subtitle_row_host.setObjectName("dashboardWelcomeSubtitleRow")
        subtitle_row_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        subtitle_row_host.setProperty("navaPreserveLayoutDirection", True)
        subtitle_row = QGridLayout(subtitle_row_host)
        subtitle_row.setContentsMargins(0, 0, 0, 0)
        subtitle_row.setHorizontalSpacing(0)
        subtitle_row.setVerticalSpacing(0)
        # Physical LTR columns: a flexible blank region on the left and the
        # one-line Persian subtitle in the right-hand column.
        subtitle_row.setColumnStretch(0, 1)
        subtitle_row.setColumnStretch(1, 0)
        subtitle_row.addWidget(subtitle, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        greeting.addWidget(eyebrow)
        greeting.addWidget(title_row_host)
        greeting.addWidget(subtitle_row_host)
        self._nava_dashboard_greeting_host = greeting_host
        self._nava_dashboard_greeting_layout = greeting
        self._nava_dashboard_title_row_host = title_row_host
        self._nava_dashboard_title_row_layout = title_row
        self._nava_dashboard_subtitle_row_host = subtitle_row_host
        self._nava_dashboard_subtitle_row_layout = subtitle_row
        self._nava_welcome_eyebrow = eyebrow
        self._nava_welcome_title = title
        self._nava_welcome_subtitle = subtitle

        local_badge = QFrame()
        self._nava_local_data_card = local_badge
        local_badge.setObjectName("localDataCard")
        local_badge.setMinimumWidth(300)
        local_badge.setMaximumWidth(322)
        local_badge.setMinimumHeight(104)
        local_badge.setMaximumHeight(116)
        local_badge.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        local_layout = QHBoxLayout(local_badge)
        local_layout.setContentsMargins(12, 10, 12, 10)
        local_layout.setSpacing(10)
        self.local_ring = ProgressRing(0, diameter=70)
        local_copy = QVBoxLayout()
        local_copy.setSpacing(4)
        local_title = QLabel("داده‌های محلی")
        local_title.setObjectName("localDataTitle")
        self.local_caption = QLabel("در حال محاسبه…")
        self.local_caption.setObjectName("localDataSize")
        self.local_detail = QLabel("پایگاه داده محلی")
        self.local_detail.setObjectName("muted")
        self.local_detail.setWordWrap(False)
        self.local_detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        local_copy.addWidget(local_title)
        local_copy.addWidget(self.local_caption)
        local_copy.addWidget(self.local_detail)
        local_layout.addWidget(self.local_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        local_layout.addLayout(local_copy, 1)
        top.addWidget(local_badge, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        top.addWidget(greeting_host, 0, 1)
        outer.addWidget(top_host)

        metrics = QGridLayout()
        metrics.setSpacing(10)
        active_palette = theme_colors()
        semantic = active_palette["semantic"]
        self.total_card = MetricCard("▤", "تمام رویدادها", active_palette["accent"])
        self.today_card = MetricCard("◷", "امروز", semantic["followup_in_progress"])
        self.favorite_card = MetricCard("✦", "علاقه‌مندی‌ها", semantic["favorite"])
        self.attachment_card = MetricCard("↗", "پیوست‌ها", semantic["followup_done"])
        self.follow_up_card = MetricCard("✓", "پیگیری", semantic["followup_pending"])
        self.importance_card = MetricCard("✦", "اهمیت", semantic["critical"])
        self.total_card.set_detail("همه رویدادها، شامل بایگانی")
        self.today_card.set_detail("بر اساس تاریخ رویداد")
        self.favorite_card.set_detail("رویدادهای نشان‌دار")
        self.attachment_card.set_detail("فایل‌ها و پوشه‌های مرتبط")
        # Six compact metric tiles share one physical row as requested.
        for index, card in enumerate((
            self.total_card, self.today_card, self.favorite_card,
            self.attachment_card, self.follow_up_card, self.importance_card,
        )):
            metrics.addWidget(card, 0, index)
            metrics.setColumnStretch(index, 1)
        metrics.setHorizontalSpacing(8)
        metrics.setVerticalSpacing(0)
        outer.addLayout(metrics)

        self.memories_button = QPushButton("مرور خاطرات  ◷")
        self.memories_button.setObjectName("dashboardMemoriesButton")
        self.memories_button.setProperty("secondary", True)
        self.memories_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.memories_button.setProperty("navaPreserveLayoutDirection", True)
        self.memories_button.setMinimumHeight(44)
        self.memories_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.memories_button.clicked.connect(self.memories_requested.emit)

        self.new_button = QPushButton("＋  ثبت رویداد تازه")
        self.new_button.setObjectName("dashboardNewEntry")
        self.new_button.setProperty("primary", True)
        self.new_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.new_button.setProperty("navaPreserveLayoutDirection", True)
        self.new_button.setMinimumHeight(44)
        self.new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_button.clicked.connect(self.new_requested.emit)
        quick_action_host = QWidget()
        quick_action_host.setObjectName("dashboardQuickActionRow")
        quick_action_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        quick_action_host.setProperty("navaPreserveLayoutDirection", True)
        quick_action_row = QHBoxLayout(quick_action_host)
        quick_action_row.setDirection(QBoxLayout.Direction.LeftToRight)
        quick_action_row.setContentsMargins(0, 0, 0, 0)
        quick_action_row.addStretch(1)
        quick_action_row.addWidget(self.memories_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        quick_action_row.addWidget(self.new_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(quick_action_host)
        self._nava_dashboard_quick_action_host = quick_action_host
        self._nava_dashboard_quick_action_layout = quick_action_row

        quote = QFrame()
        quote.setObjectName("quoteCard")
        quote_layout = QHBoxLayout(quote)
        quote_layout.setContentsMargins(20, 16, 20, 16)
        quote_layout.setSpacing(15)
        quote_rail = QFrame()
        self.quote_rail = quote_rail
        quote_rail.setFixedWidth(4)
        quote_rail.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {active_palette['accent']},stop:1 {active_palette['success']}); border-radius:2px;"
        )
        quote_layout.addWidget(quote_rail)
        quote_copy = QVBoxLayout()
        quote_copy.setSpacing(6)
        quote_heading = QLabel("✦   الهام روز")
        quote_heading.setObjectName("eyebrow")
        self.quote_text = QLabel("")
        self.quote_text.setObjectName("quoteText")
        self.quote_text.setWordWrap(True)
        self.quote_caption = QLabel("")
        self.quote_caption.setObjectName("muted")
        self.quote_caption.setWordWrap(True)
        self.quote_source_label = QLabel("در حال آماده‌سازی الهام روز…")
        self.quote_source_label.setObjectName("quoteSource")
        self.quote_source_label.setWordWrap(True)
        quote_actions = QHBoxLayout()
        quote_actions.setDirection(QBoxLayout.Direction.RightToLeft)
        quote_actions.setSpacing(8)
        self.quote_refresh_button = QPushButton("↻  تازه‌سازی")
        self.quote_refresh_button.setProperty("compact", True)
        self.quote_source_button = QPushButton("مشاهده منبع ↗")
        self.quote_source_button.setProperty("compact", True)
        quote_actions.addWidget(self.quote_source_label, 1)
        quote_actions.addStretch(1)
        quote_actions.addWidget(self.quote_refresh_button)
        quote_actions.addWidget(self.quote_source_button)
        quote_copy.addWidget(quote_heading)
        quote_copy.addWidget(self.quote_text)
        quote_copy.addWidget(self.quote_caption)
        quote_copy.addLayout(quote_actions)
        quote_layout.addLayout(quote_copy, 1)
        outer.addWidget(quote)
        self.quote_source_url = SOURCE_URL
        self.quote_refresh_button.clicked.connect(lambda: self._request_daily_inspiration(force=True))
        self.quote_source_button.clicked.connect(self._open_inspiration_source)

        section_host = QWidget()
        section_host.setObjectName("dashboardRecentHeaderRow")
        section_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        section_host.setProperty("navaPreserveLayoutDirection", True)
        # Three explicit physical columns: "view journal" at left, flexible
        # middle, heading/count badge at right. The child heading host has its
        # own LTR order, while both Persian labels remain right-aligned.
        section = QGridLayout(section_host)
        section.setContentsMargins(0, 0, 0, 0)
        section.setHorizontalSpacing(0)
        section.setVerticalSpacing(0)
        section.setColumnStretch(0, 0)
        section.setColumnStretch(1, 1)
        section.setColumnStretch(2, 0)
        view_all = QPushButton("مشاهده ژورنال  ←")
        view_all.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        view_all.setProperty("navaPreserveLayoutDirection", True)
        view_all.clicked.connect(self.view_all_requested.emit)

        heading_host = QWidget(section_host)
        heading_host.setObjectName("dashboardRecentHeadingHost")
        heading_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        heading_host.setProperty("navaPreserveLayoutDirection", True)
        heading_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        heading_group = QHBoxLayout(heading_host)
        heading_group.setDirection(QBoxLayout.Direction.LeftToRight)
        heading_group.setContentsMargins(0, 0, 0, 0)
        heading_group.setSpacing(9)
        section_title = QLabel("آخرین رویدادها")
        section_title.setObjectName("sectionTitle")
        section_title.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        section_title.setProperty("navaPreserveLayoutDirection", True)
        section_title.setProperty("navaPreserveAlignment", True)
        section_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.recent_count_label = QLabel("")
        self.recent_count_label.setObjectName("recentCountBadge")
        self.recent_count_label.setProperty("navaPreserveAlignment", True)
        self.recent_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_group.addWidget(self.recent_count_label, 0, Qt.AlignmentFlag.AlignVCenter)
        heading_group.addWidget(section_title, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        section.addWidget(view_all, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        section.addWidget(heading_host, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._nava_recent_section_layout = section
        self._nava_recent_heading_group = heading_group
        self._nava_recent_heading_host = heading_host
        self._nava_view_all_button = view_all
        self._nava_recent_header_host = section_host
        self._nava_recent_title_label = section_title
        self._nava_recent_count_label = self.recent_count_label
        outer.addWidget(section_host)

        self.recent_grid_host = QWidget()
        self.recent_grid_host.setObjectName("recentGridHost")
        self.recent_grid = QGridLayout(self.recent_grid_host)
        self.recent_grid.setContentsMargins(0, 0, 0, 0)
        self.recent_grid.setHorizontalSpacing(14)
        self.recent_grid.setVerticalSpacing(12)
        outer.addWidget(self.recent_grid_host)
        self.empty_label = QLabel("هنوز رویدادی ثبت نشده است. اولین رویدادت را ثبت کن تا ژورنال شکل بگیرد.")
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setProperty("navaPreserveCenter", True)
        self.empty_label.setMinimumHeight(115)
        self.empty_label.setWordWrap(True)
        outer.addWidget(self.empty_label)
        outer.addStretch(1)
        apply_rtl(self)
        self.enforce_local_layout()
        self._setup_daily_inspiration()
        self.refresh()

    def enforce_local_layout(self) -> None:
        """Re-pin Dashboard's physical layout and right-aligned Persian text.

        This method intentionally runs after generic RTL/LTR application and after
        cards are rebuilt, so app-wide alignment settings cannot move these pieces.
        """
        ltr = Qt.LayoutDirection.LeftToRight
        rtl = Qt.LayoutDirection.RightToLeft
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        center = Qt.AlignmentFlag.AlignCenter

        # Left storage card, right greeting column: stable physical order.
        top_host = getattr(self, "_nava_dashboard_top_host", None)
        if top_host is not None:
            top_host.setLayoutDirection(ltr)
            top_host.setProperty("navaPreserveLayoutDirection", True)
        top_layout = getattr(self, "_nava_dashboard_top_layout", None)
        if top_layout is not None:
            top_layout.setColumnStretch(0, 0)
            top_layout.setColumnStretch(1, 1)
            local_card = getattr(self, "_nava_local_data_card", None)
            if local_card is not None:
                top_layout.setAlignment(local_card, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        greeting_host = getattr(self, "_nava_dashboard_greeting_host", None)
        if greeting_host is not None:
            greeting_host.setLayoutDirection(rtl)
            greeting_host.setProperty("navaPreserveLayoutDirection", True)
        greeting = getattr(self, "_nava_dashboard_greeting_layout", None)
        if greeting is not None:
            greeting.setDirection(QBoxLayout.Direction.TopToBottom)
        title_row_host = getattr(self, "_nava_dashboard_title_row_host", None)
        if title_row_host is not None:
            title_row_host.setLayoutDirection(ltr)
            title_row_host.setProperty("navaPreserveLayoutDirection", True)
        title_row = getattr(self, "_nava_dashboard_title_row_layout", None)
        if title_row is not None:
            title_row.setColumnStretch(0, 1)
            title_row.setColumnStretch(1, 0)
            title_row.setColumnStretch(2, 0)
            title_row.setAlignment(getattr(self, "today_label", None), Qt.AlignmentFlag.AlignVCenter)
            title_row.setAlignment(getattr(self, "_nava_welcome_title", None), right)
        subtitle_host = getattr(self, "_nava_dashboard_subtitle_row_host", None)
        subtitle_row = getattr(self, "_nava_dashboard_subtitle_row_layout", None)
        subtitle = getattr(self, "_nava_welcome_subtitle", None)
        if subtitle_host is not None:
            subtitle_host.setLayoutDirection(ltr)
            subtitle_host.setProperty("navaPreserveLayoutDirection", True)
        if subtitle_row is not None:
            # QGridLayout is a physical LTR host. Column zero absorbs free
            # width; column one keeps the single-line subtitle at the right.
            subtitle_row.setColumnStretch(0, 1)
            subtitle_row.setColumnStretch(1, 0)
            if subtitle is not None:
                subtitle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                subtitle.setWordWrap(False)
                subtitle.setLayoutDirection(rtl)
                subtitle.setAlignment(right)
                subtitle.setProperty("navaPreserveAlignment", True)
                subtitle.setProperty("navaPreserveLayoutDirection", True)
                subtitle_row.setAlignment(subtitle, right)
        for name in ("_nava_welcome_eyebrow", "_nava_welcome_title", "_nava_welcome_subtitle"):
            label = getattr(self, name, None)
            if label is not None:
                label.setLayoutDirection(rtl)
                label.setAlignment(right)
                label.setProperty("navaPreserveLayoutDirection", True)
                label.setProperty("navaPreserveAlignment", True)
        if getattr(self, "today_label", None) is not None:
            self.today_label.setAlignment(center)
            self.today_label.setProperty("navaPreserveAlignment", True)

        # Quick-action button is physically at the right, regardless of app RTL/LTR mode.
        quick_host = getattr(self, "_nava_dashboard_quick_action_host", None)
        quick_row = getattr(self, "_nava_dashboard_quick_action_layout", None)
        if quick_host is not None:
            quick_host.setLayoutDirection(ltr)
            quick_host.setProperty("navaPreserveLayoutDirection", True)
        if quick_row is not None:
            quick_row.setDirection(QBoxLayout.Direction.LeftToRight)
            if getattr(self, "memories_button", None) is not None:
                quick_row.setAlignment(self.memories_button, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if getattr(self, "new_button", None) is not None:
                quick_row.setAlignment(self.new_button, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Recent heading: title/count on the right, "view journal" on the left.
        header_host = getattr(self, "_nava_recent_header_host", None)
        header_layout = getattr(self, "_nava_recent_section_layout", None)
        heading_group = getattr(self, "_nava_recent_heading_group", None)
        heading_host = getattr(self, "_nava_recent_heading_host", None)
        if header_host is not None:
            header_host.setLayoutDirection(ltr)
            header_host.setProperty("navaPreserveLayoutDirection", True)
        if header_layout is not None:
            header_layout.setColumnStretch(0, 0)
            header_layout.setColumnStretch(1, 1)
            header_layout.setColumnStretch(2, 0)
            view_all_button = getattr(self, "_nava_view_all_button", None)
            if view_all_button is not None:
                header_layout.setAlignment(view_all_button, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if heading_host is not None:
                header_layout.setAlignment(heading_host, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if heading_host is not None:
            heading_host.setLayoutDirection(ltr)
            heading_host.setProperty("navaPreserveLayoutDirection", True)
        if heading_group is not None:
            heading_group.setDirection(QBoxLayout.Direction.LeftToRight)
        view_all = getattr(self, "_nava_view_all_button", None)
        if view_all is not None:
            view_all.setLayoutDirection(ltr)
            view_all.setProperty("navaPreserveLayoutDirection", True)
        if getattr(self, "memories_button", None) is not None:
            self.memories_button.setLayoutDirection(rtl)
            self.memories_button.setProperty("navaPreserveLayoutDirection", True)
        if getattr(self, "new_button", None) is not None:
            self.new_button.setLayoutDirection(rtl)
            self.new_button.setProperty("navaPreserveLayoutDirection", True)
        recent_title = getattr(self, "_nava_recent_title_label", None)
        if recent_title is not None:
            recent_title.setAlignment(right)
            recent_title.setProperty("navaPreserveAlignment", True)
        recent_count = getattr(self, "_nava_recent_count_label", None)
        if recent_count is not None:
            recent_count.setAlignment(center)
            recent_count.setProperty("navaPreserveAlignment", True)
        grid_host = getattr(self, "recent_grid_host", None)
        if grid_host is not None:
            grid_host.setLayoutDirection(rtl)
            grid_host.setProperty("navaPreserveLayoutDirection", True)
        grid = getattr(self, "recent_grid", None)
        if grid is not None:
            for index in range(grid.count()):
                item = grid.itemAt(index)
                card = item.widget() if item is not None else None
                if isinstance(card, RecentEntryCard):
                    card.enforce_right_alignment()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Reapply fixed dashboard layout after Qt finishes inherited direction changes."""
        super().showEvent(event)
        self.enforce_local_layout()
        QTimer.singleShot(0, self.enforce_local_layout)

    def _setup_daily_inspiration(self) -> None:
        """Restore today's cached inspiration and refresh it asynchronously if needed."""
        self._quote_network = QNetworkAccessManager(self)
        self._quote_timer = QTimer(self)
        self._quote_timer.setInterval(30 * 60 * 1000)
        self._quote_timer.timeout.connect(self._check_daily_inspiration_day)
        self._quote_timer.start()
        today = date.today().isoformat()
        cached_day = str(self.settings.value("inspiration/date", "", type=str))
        cached_text = str(self.settings.value("inspiration/text", "", type=str))
        cached_author = str(self.settings.value("inspiration/author", "", type=str))
        cached_origin = str(self.settings.value("inspiration/origin", "", type=str))
        if cached_day == today and cached_text:
            item = {
                "text": cached_text,
                "author": cached_author or "ویکی‌گفتاورد فارسی",
                "source_label": str(self.settings.value("inspiration/source_label", SOURCE_LABEL, type=str)),
                "source_url": str(self.settings.value("inspiration/source_url", SOURCE_URL, type=str)),
                "date": today,
                "origin": cached_origin or "offline",
            }
            self._display_inspiration(item)
        else:
            self._display_inspiration(offline_message(date.today()))
        if cached_day != today or cached_origin != "wikiquote":
            self._request_daily_inspiration(force=True)

    def _display_inspiration(self, item: dict[str, str], status: str | None = None) -> None:
        self.quote_text.setText(item.get("text", ""))
        self.quote_caption.setText(item.get("author", ""))
        self.quote_source_url = item.get("source_url") or SOURCE_URL
        if item.get("origin") == "wikiquote":
            source = f"منبع: {item.get('source_label') or SOURCE_LABEL} · انتخاب روزانه از مجموعه گفتاورد"
        else:
            source = status or "پیام آفلاین روزنگار · برای دریافت منبع آنلاین، تازه‌سازی را بزن."
        self.quote_source_label.setText(source)
        self.quote_source_button.setEnabled(bool(self.quote_source_url))

    def _save_and_display_inspiration(self, item: dict[str, str], status: str | None = None) -> None:
        day = item.get("date") or date.today().isoformat()
        self.settings.setValue("inspiration/date", day)
        self.settings.setValue("inspiration/text", item.get("text", ""))
        self.settings.setValue("inspiration/author", item.get("author", ""))
        self.settings.setValue("inspiration/source_label", item.get("source_label", ""))
        self.settings.setValue("inspiration/source_url", item.get("source_url", SOURCE_URL))
        self.settings.setValue("inspiration/origin", item.get("origin", "offline"))
        self.settings.sync()
        self._display_inspiration(item, status)

    def _request_daily_inspiration(self, force: bool = False) -> None:
        today = date.today().isoformat()
        if self._quote_reply is not None:
            try:
                if self._quote_reply.isRunning():
                    return
            except AttributeError:
                if not self._quote_reply.isFinished():
                    return
        cached_day = str(self.settings.value("inspiration/date", "", type=str))
        cached_origin = str(self.settings.value("inspiration/origin", "", type=str))
        if not force and cached_day == today and cached_origin == "wikiquote":
            return
        self.quote_source_label.setText("در حال دریافت نقل‌قول از ویکی‌گفتاورد فارسی…")
        params = urlencode({
            "action": "query", "prop": "extracts", "explaintext": "1",
            "exchars": "24000", "titles": "گفتاورد", "format": "json", "formatversion": "2",
        })
        request = QNetworkRequest(QUrl(f"{SOURCE_API_URL}?{params}"))
        request.setRawHeader(b"User-Agent", b"NavaJournal/0.4.6 (personal desktop journal; Wikiquote source attribution)")
        request.setRawHeader(b"Accept", b"application/json")
        try:
            request.setTransferTimeout(9000)
        except AttributeError:
            pass
        reply = self._quote_network.get(request)
        self._quote_reply = reply
        reply.finished.connect(lambda r=reply, d=today: self._finish_daily_inspiration(r, d))

    def _finish_daily_inspiration(self, reply, day_key: str) -> None:
        if self._quote_reply is reply:
            self._quote_reply = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            item = parse_api_bytes(bytes(reply.readAll()), date.fromisoformat(day_key))
            self._save_and_display_inspiration(item)
        except Exception as exc:
            cached_day = str(self.settings.value("inspiration/date", "", type=str))
            cached_origin = str(self.settings.value("inspiration/origin", "", type=str))
            if cached_day != day_key or cached_origin != "wikiquote":
                fallback = offline_message(date.fromisoformat(day_key))
                self._save_and_display_inspiration(
                    fallback,
                    "منبع آنلاین در دسترس نبود؛ پیام آفلاین روزنگار نمایش داده شده است.",
                )
            else:
                self.quote_source_label.setText("آخرین نقل‌قول ذخیره‌شده نمایش داده می‌شود؛ دریافت دوباره ناموفق بود.")
            logging.getLogger(__name__).info("Daily Wikiquote refresh failed: %s", exc)
        finally:
            reply.deleteLater()

    def _check_daily_inspiration_day(self) -> None:
        today = date.today().isoformat()
        if today != self._quote_day:
            self._quote_day = today
            self._save_and_display_inspiration(offline_message(date.today()))
            self._request_daily_inspiration(force=True)

    def _open_inspiration_source(self) -> None:
        QDesktopServices.openUrl(QUrl(self.quote_source_url or SOURCE_URL))

    def _open_recent(self, entry_id: int) -> None:
        self.open_requested.emit(int(entry_id))

    def _clear_recent_cards(self) -> None:
        while self.recent_grid.count():
            item = self.recent_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                timer = getattr(widget, "_nava_fade_timer", None)
                animation = getattr(widget, "_nava_fade_animation", None)
                if timer is not None:
                    timer.stop()
                if animation is not None:
                    animation.stop()
                widget.setParent(None)
                widget.deleteLater()

    def apply_theme_colors(self) -> None:
        palette = theme_colors()
        semantic = palette["semantic"]
        self.total_card.set_accent(palette["accent"])
        self.today_card.set_accent(semantic["followup_in_progress"])
        self.favorite_card.set_accent(semantic["favorite"])
        self.attachment_card.set_accent(semantic["followup_done"])
        self.follow_up_card.set_accent(semantic["followup_pending"])
        self.importance_card.set_accent(semantic["critical"])
        self.quote_rail.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {palette['accent']},stop:1 {palette['success']}); border-radius:2px;"
        )

    def refresh(self) -> None:
        self.apply_theme_colors()
        stats = self.repository.stats()
        self.total_card.set_value(stats["total"])
        self.today_card.set_value(stats["today"])
        self.favorite_card.set_value(stats["favorites"])
        self.attachment_card.set_value(stats["attachments"])
        self.follow_up_card.set_value(stats["follow_up_total"])
        self.follow_up_card.set_detail(
            f"بدون {display_digits(stats['follow_up_none'])}  ·  نیازمند {display_digits(stats['follow_up_pending'])}  ·  در جریان {display_digits(stats['follow_up_in_progress'])}  ·  انجام‌شده {display_digits(stats['follow_up_done'])}"
        )
        self.importance_card.set_value(stats["importance_total"])
        self.importance_card.set_detail(
            f"عادی {display_digits(stats['importance_normal'])}  ·  مهم {display_digits(stats['importance_important'])}  ·  فوری {display_digits(stats['importance_critical'])}"
        )
        self.today_label.setText(f"امروز  ·  {display_digits(format_jalali(jalali_iso_today()))}")
        # The local-data card reports the actual database and its WAL/SHM sidecars,
        # not a decorative progress value. Path is imported at module scope for this.
        try:
            db_path = self.repository.db.path
            # In WAL mode, recently written rows may reside beside the main file.
            bytes_used = sum(
                candidate.stat().st_size for candidate in (
                    db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")
                ) if candidate.exists()
            )
            if bytes_used < 1024 * 1024:
                size_text = f"{display_digits(max(1, round(bytes_used / 1024)))} KB"
            else:
                size_text = f"{display_digits(f'{bytes_used / (1024 * 1024):.1f}')} MB"
            # A 250 MB visual scale is an indicator only, not a storage limit.
            percent = int(min(100, max(1 if bytes_used else 0, round(bytes_used / (250 * 1024 * 1024) * 100))))
            self.local_ring.set_value(percent)
            self.local_caption.setText(size_text)
            self.local_detail.setText(
                f"{display_digits(stats['total'])} رویداد  ·  {display_digits(stats['attachments'])} پیوست"
            )
            self.local_detail.setToolTip(f"مسیر پایگاه داده:\n{db_path}\nاندازه شامل فایل اصلی، WAL و SHM است.")
        except (OSError, AttributeError, RuntimeError):
            self.local_ring.set_value(0)
            self.local_caption.setText("در دسترس نیست")
            self.local_detail.setText("مسیر پایگاه داده را بررسی کن")
        entries = self.repository.list_entries(limit=6)
        self._clear_recent_cards()
        for index, entry in enumerate(entries):
            card = RecentEntryCard(entry, index, self.recent_grid_host)
            card.opened.connect(self._open_recent)
            self.recent_grid.addWidget(card, index // 2, index % 2)
        self.recent_grid_host.setVisible(bool(entries))
        self.empty_label.setVisible(not entries)
        self.recent_count_label.setText(f"{display_digits(len(entries))} مورد تازه")
        self.enforce_local_layout()


class MemoryEntryCard(QFrame):
    """Compact exclusive-accordion item for one historical memory."""
    opened = Signal(int)
    expanded_changed = Signal(int, bool)

    IMPORTANCE_LABELS = {"normal": "عادی", "important": "مهم", "critical": "فوری / بحرانی"}
    FOLLOWUP_LABELS = {"none": "بدون پیگیری", "pending": "نیازمند پیگیری", "in_progress": "در حال انجام", "done": "انجام شده"}

    def __init__(self, entry: dict, parent: QWidget | None = None, expanded: bool = False) -> None:
        super().__init__(parent)
        self.entry_id = int(entry["id"])
        self._expanded = False
        self.setObjectName("memoryEntryCard")
        self.setProperty("navaForceRtl", True)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(9, 9, 9, 9)
        outer.setSpacing(4)

        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("memoryAccordionToggle")
        self.toggle_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setAccessibleName(f"باز یا بسته کردن خاطره: {entry.get('title', '')}")
        header_layout = QHBoxLayout(self.toggle_button)
        header_layout.setContentsMargins(13, 10, 13, 10)
        header_layout.setSpacing(13)
        header_layout.setDirection(QBoxLayout.Direction.RightToLeft)

        header_copy = QVBoxLayout()
        header_copy.setContentsMargins(0, 0, 0, 0)
        header_copy.setSpacing(5)
        title = QLabel(str(entry.get("title") or "بدون عنوان"))
        title.setObjectName("memoryEntryTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        title.setWordWrap(True)
        meta_parts = []
        date_value = str(entry.get("event_jalali_date") or "")
        if len(date_value) >= 10:
            meta_parts.append(display_digits(date_value.replace("-", ".")))
        meta_parts.append(str(entry.get("category_name") or "بدون دسته"))
        person_name = str(entry.get("person_name") or "").strip()
        if person_name:
            meta_parts.append(f"شخص مرتبط: {person_name}")
        if int(entry.get("is_favorite") or 0):
            meta_parts.append("★ علاقه‌مندی")
        if int(entry.get("is_archived") or 0):
            meta_parts.append("بایگانی")
        meta = QLabel("   ·   ".join(meta_parts))
        meta.setObjectName("memoryAccordionMeta")
        meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meta.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        meta.setWordWrap(True)
        header_copy.addWidget(title)
        header_copy.addWidget(meta)
        header_layout.addLayout(header_copy, 1)

        self.arrow_label = QLabel("⌃" if expanded else "⌄")
        self.arrow_label.setObjectName("memoryAccordionArrow")
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow_label.setFixedSize(34, 34)
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow_label.setProperty("navaPreserveCenter", True)
        self.arrow_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        header_layout.addWidget(self.arrow_label, 0, Qt.AlignmentFlag.AlignVCenter)
        # Clicks on label children are passed to the containing button.
        for label in (title, meta, self.arrow_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        outer.addWidget(self.toggle_button)

        self.details = QFrame()
        self.details.setObjectName("memoryAccordionDetails")
        self.details.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(18, 15, 18, 15)
        details_layout.setSpacing(11)
        body_text = " ".join(str(entry.get("body") or "").split())
        self.body_label = QLabel(body_text if body_text else "برای این رویداد یادداشتی ثبت نشده است.")
        self.body_label.setObjectName("memoryAccordionBody")
        self.body_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.body_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.body_label.setWordWrap(True)
        self.body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.body_label)

        status_parts = [
            f"اهمیت: {self.IMPORTANCE_LABELS.get(str(entry.get('importance') or 'normal'), 'عادی')}",
            f"پیگیری: {self.FOLLOWUP_LABELS.get(str(entry.get('follow_up_status') or 'none'), 'بدون پیگیری')}",
        ]
        status_label = QLabel("   ·   ".join(status_parts))
        status_label.setObjectName("memoryAccordionMeta")
        status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        details_layout.addWidget(status_label)

        tag_names = str(entry.get("tag_names") or "").strip()
        if tag_names:
            tags_label = QLabel(f"برچسب‌ها: {tag_names}")
            tags_label.setObjectName("memoryAccordionTags")
            tags_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tags_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            tags_label.setWordWrap(True)
            details_layout.addWidget(tags_label)

        attachment_count = int(entry.get("attachment_count") or 0)
        if attachment_count:
            attachment_label = QLabel(f"پیوست‌های مرتبط: {display_digits(attachment_count)} فایل")
            attachment_label.setObjectName("memoryAccordionMeta")
            attachment_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            attachment_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            details_layout.addWidget(attachment_label)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 2, 0, 0)
        action_row.setDirection(QBoxLayout.Direction.RightToLeft)
        self.open_button = QPushButton("بازکردن رویداد برای مشاهده و ویرایش  ←")
        self.open_button.setProperty("secondary", True)
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(lambda _checked=False: self.opened.emit(self.entry_id))
        action_row.addWidget(self.open_button)
        action_row.addStretch(1)
        details_layout.addLayout(action_row)
        outer.addWidget(self.details)

        self.toggle_button.clicked.connect(self._toggle_expanded)
        self.set_expanded(expanded, emit=False)
        self.enforce_rtl()

    def _toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded, emit=True)

    def set_expanded(self, expanded: bool, emit: bool = True) -> None:
        expanded = bool(expanded)
        changed = expanded != self._expanded
        self._expanded = expanded
        self.details.setVisible(expanded)
        self.arrow_label.setText("⌃" if expanded else "⌄")
        self.setProperty("expanded", "true" if expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if changed and emit:
            self.expanded_changed.emit(self.entry_id, expanded)

    def enforce_rtl(self) -> None:
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.toggle_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        if self.layout() is not None:
            self.layout().setDirection(QBoxLayout.Direction.TopToBottom)
        header_layout = self.toggle_button.layout()
        if isinstance(header_layout, QBoxLayout):
            header_layout.setDirection(QBoxLayout.Direction.RightToLeft)
        for widget in self.findChildren(QWidget):
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            if isinstance(widget, QLabel):
                if widget.objectName() == "memoryAccordionArrow":
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if self.body_label is not None:
            self.body_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)


class MemoriesPage(QWidget):
    """An RTL-first, modern editorial timeline of this day in previous years."""
    open_requested = Signal(int)
    new_requested = Signal()

    def __init__(self, repository, settings=None) -> None:
        super().__init__()
        self.repository = repository
        self.settings = settings or QSettings()
        self.setObjectName("memoriesPage")
        self.setProperty("navaForceRtl", True)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("memoriesScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        canvas = QWidget()
        canvas.setObjectName("memoriesCanvas")
        canvas.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        canvas.setProperty("navaForceRtl", True)
        self.canvas = canvas
        content = QVBoxLayout(canvas)
        content.setContentsMargins(32, 28, 32, 34)
        content.setSpacing(22)
        self.scroll_area.setWidget(canvas)
        root_layout.addWidget(self.scroll_area)

        # Header row: clear hierarchy, generous whitespace and a real action.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(18)
        header_row.setDirection(QBoxLayout.Direction.RightToLeft)
        header_copy = QVBoxLayout()
        header_copy.setContentsMargins(0, 0, 0, 0)
        header_copy.setSpacing(5)
        eyebrow = QLabel("NAVA JOURNAL  /  حافظهٔ شخصی")
        eyebrow.setObjectName("eyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        eyebrow.setProperty("navaPreserveAlignment", True)
        title = QLabel("مرور خاطرات")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title.setProperty("navaPreserveAlignment", True)
        subtitle = QLabel("لحظه‌هایی را دوباره پیدا کن که در همین روز، در سال‌های گذشته ثبت کرده‌ای.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        subtitle.setProperty("navaPreserveAlignment", True)
        header_copy.addWidget(eyebrow)
        header_copy.addWidget(title)
        header_copy.addWidget(subtitle)
        header_row.addLayout(header_copy, 1)
        self.refresh_button = QPushButton("↻  تازه‌سازی")
        self.refresh_button.setProperty("secondary", True)
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(header_row)

        # Large featured panel: one sentence, one date, no crowded toolbar controls.
        self.hero = QFrame()
        self.hero.setObjectName("memoryHero")
        self.hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(18)
        hero_layout.setDirection(QBoxLayout.Direction.RightToLeft)

        hero_mark = QFrame()
        hero_mark.setObjectName("memoryHeroMark")
        hero_mark.setFixedSize(64, 64)
        hero_mark_layout = QVBoxLayout(hero_mark)
        hero_mark_layout.setContentsMargins(0, 0, 0, 0)
        glyph = QLabel("↶")
        glyph.setObjectName("memoryHeroGlyph")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setProperty("navaPreserveAlignment", True)
        glyph.setProperty("navaPreserveCenter", True)
        hero_mark_layout.addWidget(glyph)
        hero_layout.addWidget(hero_mark, 0, Qt.AlignmentFlag.AlignVCenter)

        hero_copy = QVBoxLayout()
        hero_copy.setContentsMargins(0, 0, 0, 0)
        hero_copy.setSpacing(7)
        self.hero_kicker = QLabel("امروز در گذشته")
        self.hero_kicker.setObjectName("memoryHeroKicker")
        self.hero_kicker.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.hero_kicker.setProperty("navaPreserveAlignment", True)
        self.hero_title = QLabel("خاطراتت، در گذر زمان")
        self.hero_title.setObjectName("memoryHeroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.hero_title.setProperty("navaPreserveAlignment", True)
        self.hero_subtitle = QLabel("مروری آرام بر ردپای روزهای گذشته.")
        self.hero_subtitle.setObjectName("memoryHeroSubtitle")
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.hero_subtitle.setProperty("navaPreserveAlignment", True)
        self.hero_subtitle.setWordWrap(True)
        hero_copy.addWidget(self.hero_kicker)
        hero_copy.addWidget(self.hero_title)
        hero_copy.addWidget(self.hero_subtitle)
        hero_layout.addLayout(hero_copy, 1)

        date_wrap = QFrame()
        date_wrap.setObjectName("memoryHeroDateWrap")
        date_wrap.setMinimumWidth(158)
        date_wrap_layout = QVBoxLayout(date_wrap)
        date_wrap_layout.setContentsMargins(16, 13, 16, 13)
        date_wrap_layout.setSpacing(5)
        date_caption = QLabel("تاریخ امروز")
        date_caption.setObjectName("memoryTodayLabel")
        date_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_caption.setProperty("navaPreserveAlignment", True)
        date_caption.setProperty("navaPreserveCenter", True)
        self.hero_date = QLabel("")
        self.hero_date.setObjectName("memoryHeroDate")
        self.hero_date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_date.setProperty("navaPreserveAlignment", True)
        self.hero_date.setProperty("navaPreserveCenter", True)
        date_wrap_layout.addWidget(date_caption)
        date_wrap_layout.addWidget(self.hero_date)
        hero_layout.addWidget(date_wrap, 0, Qt.AlignmentFlag.AlignVCenter)
        content.addWidget(self.hero)

        # Compact status strip gives the page a dashboard-like information rhythm.
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(12)
        stats_row.setDirection(QBoxLayout.Direction.RightToLeft)
        self.stat_count_value, self.stat_count_card = self._make_stat_card("۰", "خاطره در این روز")
        self.stat_years_value, self.stat_years_card = self._make_stat_card("۰", "سال متفاوت")
        self.stat_day_value, self.stat_day_card = self._make_stat_card("—", "روز مورد مرور")
        for card in (self.stat_count_card, self.stat_years_card, self.stat_day_card):
            stats_row.addWidget(card, 1)
        content.addLayout(stats_row)

        section_row = QHBoxLayout()
        section_row.setContentsMargins(0, 0, 0, 0)
        section_row.setSpacing(10)
        section_row.setDirection(QBoxLayout.Direction.RightToLeft)
        section_title = QLabel("خاطرات این روز")
        section_title.setObjectName("sectionTitle")
        section_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        section_title.setProperty("navaPreserveAlignment", True)
        self.count_badge = QLabel("۰ خاطره")
        self.count_badge.setObjectName("recentCountBadge")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_badge.setProperty("navaPreserveAlignment", True)
        self.count_badge.setProperty("navaPreserveCenter", True)
        section_row.addWidget(section_title)
        section_row.addWidget(self.count_badge)
        section_row.addStretch(1)
        content.addLayout(section_row)

        self.entries_host = QWidget()
        self.entries_host.setObjectName("memoryEntriesHost")
        self.entries_host.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.entries_layout = QVBoxLayout(self.entries_host)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        self.entries_layout.setSpacing(14)
        content.addWidget(self.entries_host)

        self.empty_state = QFrame()
        self.empty_state.setObjectName("memoryEmptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(28, 30, 28, 30)
        empty_layout.setSpacing(10)
        empty_mark = QLabel("✦")
        empty_mark.setObjectName("memoryEmptyMark")
        empty_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_mark.setProperty("navaPreserveCenter", True)
        empty_title = QLabel("این صفحه منتظر اولین خاطرهٔ توست")
        empty_title.setObjectName("sectionTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setProperty("navaPreserveCenter", True)
        empty_copy = QLabel("رویدادی برای این روز در سال‌های گذشته پیدا نشد. می‌توانی از امروز خاطره‌ای ثبت کنی تا در سال‌های آینده به اینجا برگردد.")
        empty_copy.setObjectName("muted")
        empty_copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_copy.setProperty("navaPreserveCenter", True)
        empty_copy.setWordWrap(True)
        self.new_today_button = QPushButton("＋  ثبت رویداد امروز")
        self.new_today_button.setProperty("primary", True)
        self.new_today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_today_button.clicked.connect(self.new_requested.emit)
        empty_layout.addWidget(empty_mark)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_copy)
        empty_layout.addSpacing(5)
        empty_layout.addWidget(self.new_today_button, 0, Qt.AlignmentFlag.AlignHCenter)
        content.addWidget(self.empty_state)
        content.addStretch(1)

        apply_rtl(self)
        self.enforce_local_layout()
        self.refresh()

    def enforce_local_layout(self) -> None:
        """Keep this Persian editorial timeline RTL even if global preferences were LTR/left."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        for widget in (self.scroll_area, self.canvas, self.hero, self.entries_host, self.empty_state):
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            widget.setProperty("navaForceRtl", True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        # Explicitly make horizontal rows read from the Persian edge, rather than
        # letting a parent layout-direction change mirror one page inconsistently.
        for layout in self.findChildren(QBoxLayout):
            if layout.direction() in (QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.RightToLeft):
                layout.setDirection(QBoxLayout.Direction.RightToLeft)
        for card in self.entries_host.findChildren(MemoryEntryCard):
            card.enforce_rtl()
        for widget in self.findChildren(QWidget):
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            if isinstance(widget, QLabel):
                if widget.property("navaPreserveCenter") or widget.objectName() == "memoryAccordionArrow":
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    current = widget.alignment()
                    vertical = current & (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignVCenter)
                    widget.setAlignment(Qt.AlignmentFlag.AlignRight | (vertical or Qt.AlignmentFlag.AlignVCenter))
                widget.setProperty("navaPreserveAlignment", True)
                widget.setProperty("navaPreserveLayoutDirection", True)
        # Buttons should also inherit RTL so glyphs do not end up on the English edge.
        for button in self.findChildren(QPushButton):
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            button.setProperty("navaPreserveLayoutDirection", True)

    def _on_card_expanded_changed(self, entry_id: int, expanded: bool) -> None:
        if not expanded:
            return
        for card in self.entries_host.findChildren(MemoryEntryCard):
            if card.entry_id != int(entry_id):
                card.set_expanded(False, emit=False)

    @staticmethod
    def _make_stat_card(value: str, label: str) -> tuple[QLabel, QFrame]:
        card = QFrame()
        card.setObjectName("memoryStatCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(17, 13, 17, 13)
        layout.setSpacing(3)
        value_label = QLabel(value)
        value_label.setObjectName("memoryStatValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setProperty("navaPreserveAlignment", True)
        label_widget = QLabel(label)
        label_widget.setObjectName("memoryStatLabel")
        label_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label_widget.setProperty("navaPreserveAlignment", True)
        layout.addWidget(value_label)
        layout.addWidget(label_widget)
        return value_label, card

    def refresh(self) -> None:
        today = current_jalali()
        jalali_today = f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
        self.hero_date.setText(display_digits(format_jalali_full(jalali_iso_today(), separator=".")))
        self.hero_subtitle.setText(
            f"رویدادهایی که در {MONTHS[today.month - 1]} {display_digits(today.day)}، در سال‌های گذشته ثبت شده‌اند."
        )
        entries = self.repository.memories_on_this_day(jalali_today)
        while self.entries_layout.count():
            item = self.entries_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, entry in enumerate(entries):
            # A single expanded item keeps the timeline compact; scroll reveals the
            # next cards naturally and opening one collapses its sibling.
            card = MemoryEntryCard(entry, self.entries_host, expanded=(index == 0))
            card.opened.connect(self.open_requested.emit)
            card.expanded_changed.connect(self._on_card_expanded_changed)
            self.entries_layout.addWidget(card)
        self.entries_host.setVisible(bool(entries))
        self.empty_state.setVisible(not entries)
        count = len(entries)
        years = {str(item.get("event_jalali_date") or "")[:4] for item in entries if len(str(item.get("event_jalali_date") or "")) >= 4}
        self.count_badge.setText(f"{display_digits(count)} خاطره")
        self.stat_count_value.setText(display_digits(count))
        self.stat_years_value.setText(display_digits(len(years)))
        self.stat_day_value.setText(display_digits(f"{today.month:02d}.{today.day:02d}"))
        self.hero_title.setText("امروز، فصل‌های قبلی زندگی‌ات" if entries else "از امروز، خاطره‌ای برای آینده بساز")
        self.hero_kicker.setText("امروز در گذشته")
        self.enforce_local_layout()


SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class SortableTableItem(QTableWidgetItem):
    """Table item that sorts using a canonical value, not just its display text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(SORT_ROLE)
        right = other.data(SORT_ROLE)
        if left is not None and right is not None:
            try:
                return left < right
            except TypeError:
                return str(left).casefold() < str(right).casefold()
        return super().__lt__(other)


def _sort_item(text: str, value: object, entry_id: int) -> SortableTableItem:
    item = SortableTableItem(text)
    app = QApplication.instance()
    selected_font = str(app.property("nava_numeric_font_family") or (app.font().family() if app else "Tahoma")) if app else "Tahoma"
    item.setFont(QFont(selected_font, 9))
    item.setTextAlignment(table_alignment_flags())
    item.setData(SORT_ROLE, value)
    item.setData(Qt.ItemDataRole.UserRole, entry_id)
    return item


class JournalPage(QWidget):
    new_requested = Signal()
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    archive_requested = Signal(int)
    restore_requested = Signal(int)
    favorite_requested = Signal(int)

    HEADERS = [
        "تاریخ شمسی", "عنوان رویداد", "دسته‌بندی", "شخص", "وضعیت پیگیری", "اهمیت",
        "برچسب‌ها", "پیوست‌ها", "زمان ثبت", "آخرین تغییر", "علاقه‌مندی",
    ]

    def __init__(self, repository, archived: bool = False, settings: QSettings | None = None) -> None:
        super().__init__()
        self.repository = repository
        self.archived = archived
        self.settings = settings if settings is not None else QSettings()
        self._header_restoring = True
        self._header_state_key = f"journal/table_state/v2/{'archive' if archived else 'active'}"
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        sort_scope = "archive" if archived else "active"
        try:
            self._sort_column = max(0, min(len(self.HEADERS) - 1, int(self.settings.value(f"journal/sort/{sort_scope}/column", 0))))
            self._sort_order = Qt.SortOrder(int(self.settings.value(f"journal/sort/{sort_scope}/order", int(Qt.SortOrder.DescendingOrder))))
        except (TypeError, ValueError):
            self._sort_column = 0
            self._sort_order = Qt.SortOrder.DescendingOrder
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 25, 28, 22)
        outer.setSpacing(17)

        header_host = QWidget()
        header_host.setObjectName("journalHeaderRow")
        header_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        header_host.setProperty("navaPreserveLayoutDirection", True)
        header = QHBoxLayout(header_host)
        header.setDirection(QBoxLayout.Direction.LeftToRight)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)
        title_column = QVBoxLayout()
        title_column.setSpacing(5)
        eyebrow = QLabel("YOUR LIBRARY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("بایگانی رویدادها" if archived else "ژورنال من")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "موارد قدیمی را پیدا کن، ویرایش کن و بر اساس هر ستون مرتب کن."
            if archived else
            "سرستون هر فیلد را بزن تا صعودی یا نزولی مرتب شود؛ تاریخ نمایشی کوتاه است اما مرتب‌سازی از سال کامل استفاده می‌کند."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_column.addWidget(eyebrow)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column, 1)
        self._nava_header_layout = header
        self._nava_title_column = title_column
        self.new_button = QPushButton("＋  رویداد تازه")
        self.new_button.setProperty("primary", True)
        self.new_button.setVisible(not archived)
        self.new_button.setMinimumHeight(44)
        self.new_button.clicked.connect(self.new_requested.emit)
        header.addWidget(self.new_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        outer.addWidget(header_host)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.search_edit.setPlaceholderText("جست‌وجو در عنوان، متن، دسته، شخص یا نام فایل…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)
        self.category_combo = NoWheelComboBox()
        self.person_combo = NoWheelComboBox()
        self.category_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.person_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.category_combo.setMaximumWidth(190)
        self.person_combo.setMaximumWidth(180)
        self.favorite_check = QCheckBox("فقط علاقه‌مندی‌ها")
        self.advanced_button = QPushButton("⌕ جست‌وجوی پیشرفته")
        self.advanced_button.setCheckable(True)
        self.refresh_button = QPushButton("↻ تازه‌سازی")
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.category_combo)
        filters.addWidget(self.person_combo)
        filters.addWidget(self.favorite_check)
        filters.addWidget(self.advanced_button)
        filters.addWidget(self.refresh_button)
        outer.addLayout(filters)

        self.advanced_panel = QFrame()
        self.advanced_panel.setObjectName("advancedSearchCard")
        self.advanced_panel.setProperty("navaForceRtl", True)
        self.advanced_panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.advanced_panel.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced_panel)
        self.advanced_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        advanced_layout.setContentsMargins(18, 17, 18, 16)
        advanced_layout.setSpacing(13)
        date_row = QHBoxLayout()
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.setSpacing(12)
        from_box = QVBoxLayout()
        from_box.setSpacing(7)
        from_label = QLabel("از تاریخ شمسی")
        from_label.setObjectName("fieldLabel")
        from_label.setMinimumHeight(22)
        self.date_from_edit = QLineEdit()
        self.date_from_edit.setMinimumHeight(44)
        self.date_from_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.date_from_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_from_edit.setProperty("navaPreserveCenter", True)
        self.date_from_edit.setPlaceholderText("مثلاً 05.08.01")
        from_box.addWidget(from_label)
        from_box.addWidget(self.date_from_edit)
        to_box = QVBoxLayout()
        to_box.setSpacing(7)
        to_label = QLabel("تا تاریخ شمسی")
        to_label.setObjectName("fieldLabel")
        to_label.setMinimumHeight(22)
        self.date_to_edit = QLineEdit()
        self.date_to_edit.setMinimumHeight(44)
        self.date_to_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.date_to_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_to_edit.setProperty("navaPreserveCenter", True)
        self.date_to_edit.setPlaceholderText("مثلاً 05.08.30")
        to_box.addWidget(to_label)
        to_box.addWidget(self.date_to_edit)
        date_row.addLayout(from_box, 1)
        date_row.addLayout(to_box, 1)
        self.apply_advanced_button = QPushButton("اعمال فیلترها")
        self.apply_advanced_button.setProperty("primary", True)
        date_row.addWidget(self.apply_advanced_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.clear_advanced_button = QPushButton("پاک‌کردن")
        date_row.addWidget(self.clear_advanced_button, 0, Qt.AlignmentFlag.AlignBottom)
        advanced_layout.addLayout(date_row)
        tracking_filter_row = QHBoxLayout()
        tracking_filter_row.setContentsMargins(0, 0, 0, 0)
        tracking_filter_row.setSpacing(12)
        importance_filter_box = QVBoxLayout()
        importance_filter_box.setSpacing(6)
        importance_filter_label = QLabel("اهمیت")
        importance_filter_label.setObjectName("fieldLabel")
        importance_filter_label.setMinimumHeight(22)
        self.importance_filter_combo = NoWheelComboBox()
        self.importance_filter_combo.setMinimumHeight(44)
        self.importance_filter_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.importance_filter_combo.addItem("همه اهمیت‌ها", None)
        for label, value in (("عادی", "normal"), ("مهم", "important"), ("فوری / بحرانی", "critical")):
            self.importance_filter_combo.addItem(label, value)
        importance_filter_box.addWidget(importance_filter_label)
        importance_filter_box.addWidget(self.importance_filter_combo)
        status_filter_box = QVBoxLayout()
        status_filter_box.setSpacing(6)
        status_filter_label = QLabel("وضعیت پیگیری")
        status_filter_label.setObjectName("fieldLabel")
        status_filter_label.setMinimumHeight(22)
        self.follow_up_filter_combo = NoWheelComboBox()
        self.follow_up_filter_combo.setMinimumHeight(44)
        self.follow_up_filter_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.follow_up_filter_combo.addItem("همه وضعیت‌ها", None)
        for label, value in (("بدون پیگیری", "none"), ("نیازمند پیگیری", "pending"), ("در حال انجام", "in_progress"), ("انجام شده", "done")):
            self.follow_up_filter_combo.addItem(label, value)
        status_filter_box.addWidget(status_filter_label)
        status_filter_box.addWidget(self.follow_up_filter_combo)
        tracking_filter_row.addLayout(importance_filter_box, 1)
        tracking_filter_row.addLayout(status_filter_box, 1)
        tracking_filter_row.addStretch(1)
        advanced_layout.addLayout(tracking_filter_row)
        tag_label = QLabel("برچسب‌های مورد جست‌وجو · انتخاب چند مورد، تطبیق با هرکدام")
        tag_label.setObjectName("fieldLabel")
        tag_label.setMinimumHeight(24)
        advanced_layout.addWidget(tag_label)
        self.tags_filter_list = QListWidget()
        self.tags_filter_list.setObjectName("filterTagList")
        self.tags_filter_list.setMinimumHeight(100)
        self.tags_filter_list.setMaximumHeight(126)
        self.tags_filter_list.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tags_filter_list.setFlow(QListWidget.Flow.LeftToRight)
        self.tags_filter_list.setWrapping(True)
        advanced_layout.addWidget(self.tags_filter_list)
        self.advanced_error = QLabel("")
        self.advanced_error.setObjectName("warningText")
        self.advanced_error.setWordWrap(True)
        self.advanced_error.hide()
        advanced_layout.addWidget(self.advanced_error)
        outer.addWidget(self.advanced_panel)
        self.refresh_reference_filters(refresh=False)

        table_card = QFrame()
        table_card.setObjectName("surfaceCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        header_view = self.table.horizontalHeader()
        header_view.setSectionsClickable(True)
        header_view.setSectionsMovable(True)
        header_view.setSortIndicatorShown(True)
        header_view.setStretchLastSection(False)
        header_view.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header_view.customContextMenuRequested.connect(self._show_column_menu)
        for column in range(len(self.HEADERS)):
            header_item = self.table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip("برای مرتب‌سازی کلیک کن؛ برای جابه‌جایی بکش؛ راست‌کلیک برای نمایش/پنهان‌کردن ستون‌ها.")
        # Compact defaults fit the common 1366x768/1280x720 laptop viewport;
        # every column remains user-resizable and the complete layout is persisted.
        default_widths = (74, 152, 80, 70, 88, 70, 88, 56, 120, 120, 50)
        for col, width in enumerate(default_widths):
            header_view.resizeSection(col, width)
        saved_header_state = self.settings.value(self._header_state_key)
        migrated_legacy_state = False
        if not saved_header_state:
            # Preserve a user's pre-0.4.1 choices (order/visibility/size) instead of
            # silently discarding them; the new key only changes the default layout.
            legacy_key = f"journal/table_state/{'archive' if archived else 'active'}"
            saved_header_state = self.settings.value(legacy_key)
            migrated_legacy_state = bool(saved_header_state)
        restored = False
        if saved_header_state:
            try:
                restored = bool(header_view.restoreState(saved_header_state))
            except (TypeError, RuntimeError):
                restored = False
        if not restored:
            saved_header_state = None
            migrated_legacy_state = False
            # Less frequently used metadata stays available in the column menu but
            # hidden by default to avoid horizontal scrolling on laptop screens.
            self.table.setColumnHidden(8, True)
            self.table.setColumnHidden(9, True)
        elif migrated_legacy_state:
            # Older defaults were much wider. Keep the user's custom order and
            # visibility but compact the widths once so laptop screens fit by default.
            visible_width = sum(
                header_view.sectionSize(column)
                for column in range(len(self.HEADERS))
                if not self.table.isColumnHidden(column)
            )
            target_width = 728
            minimum_widths = {0: 72, 1: 120, 2: 72, 3: 65, 4: 78, 5: 65, 6: 78, 7: 52, 8: 110, 9: 110, 10: 45}
            if visible_width > target_width:
                scale = target_width / visible_width
                for column in range(len(self.HEADERS)):
                    if self.table.isColumnHidden(column):
                        continue
                    old_width = header_view.sectionSize(column)
                    header_view.resizeSection(column, max(minimum_widths.get(column, 50), int(old_width * scale)))
        self._header_restoring = False
        header_view.sectionMoved.connect(self._save_header_state)
        header_view.sectionResized.connect(self._save_header_state)
        header_view.sortIndicatorChanged.connect(self._remember_sort)
        if migrated_legacy_state:
            self._save_header_state()
        # The viewport emits row coordinates relative to the item area (not the header).
        self.table.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.viewport().customContextMenuRequested.connect(self._show_row_menu)
        self.table.cellDoubleClicked.connect(self._edit_selected_row)
        self.table.cellClicked.connect(self._table_cell_clicked)
        table_layout.addWidget(self.table)
        outer.addWidget(table_card, 1)

        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.LeftToRight)
        self.count_label = QLabel("")
        self.count_label.setObjectName("journalCountBadge")
        actions.addWidget(self.count_label)
        actions.addStretch(1)
        self.edit_button = QPushButton("ویرایش انتخاب‌شده")
        self.archive_button = QPushButton("بازیابی از بایگانی" if archived else "انتقال به بایگانی")
        self.delete_button = QPushButton("حذف دائمی")
        self.delete_button.setProperty("danger", True)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.archive_button)
        actions.addWidget(self.delete_button)
        outer.addLayout(actions)

        for compact_combo in (self.category_combo, self.person_combo, self.importance_filter_combo, self.follow_up_filter_combo):
            compact_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            compact_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            fit_combo_to_contents(compact_combo, maximum_width=240)

        self.search_edit.textChanged.connect(self.refresh)
        self.category_combo.currentIndexChanged.connect(self.refresh)
        self.person_combo.currentIndexChanged.connect(self.refresh)
        self.favorite_check.toggled.connect(self.refresh)
        self.advanced_button.toggled.connect(self._set_advanced_search_visible)
        self.apply_advanced_button.clicked.connect(self.refresh)
        self.clear_advanced_button.clicked.connect(self._clear_advanced_filters)
        self.date_from_edit.returnPressed.connect(self.refresh)
        self.date_to_edit.returnPressed.connect(self.refresh)
        self.importance_filter_combo.currentIndexChanged.connect(self.refresh)
        self.follow_up_filter_combo.currentIndexChanged.connect(self.refresh)
        self.tags_filter_list.itemChanged.connect(lambda _item: self.refresh())
        self.refresh_button.clicked.connect(self.refresh)
        self.edit_button.clicked.connect(self._edit_current)
        self.delete_button.clicked.connect(self._delete_current)
        self.archive_button.clicked.connect(self._archive_current)
        self.refresh()

    def _save_header_state(self, *_: object) -> None:
        if getattr(self, "_header_restoring", True):
            return
        try:
            self.settings.setValue(self._header_state_key, self.table.horizontalHeader().saveState())
            self.settings.sync()
        except RuntimeError:
            pass

    def _show_column_menu(self, position) -> None:
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        for column, label in enumerate(self.HEADERS):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.toggled.connect(lambda visible, col=column: self._set_column_visible(col, visible))
        menu.addSeparator()
        show_all = menu.addAction("نمایش همه ستون‌ها")
        hide_optional = menu.addAction("پنهان‌کردن ستون‌های کم‌استفاده")
        selected = menu.exec(self.table.horizontalHeader().mapToGlobal(position))
        if selected is show_all:
            for column in range(len(self.HEADERS)):
                self.table.setColumnHidden(column, False)
            self._save_header_state()
        elif selected is hide_optional:
            for column in (8, 9):
                self.table.setColumnHidden(column, True)
            self._save_header_state()

    def _set_column_visible(self, column: int, visible: bool) -> None:
        self.table.setColumnHidden(column, not visible)
        self._save_header_state()

    def _show_row_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        self.table.setCurrentCell(index.row(), index.column())
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        edit = menu.addAction("ویرایش رویداد")
        favorite = menu.addAction("تغییر علاقه‌مندی")
        menu.addSeparator()
        archive_label = "بازیابی از بایگانی" if self.archived else "انتقال به بایگانی"
        archive = menu.addAction(archive_label)
        delete = menu.addAction("حذف دائمی")
        delete.setEnabled(True)
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        entry_id = self.selected_entry_id()
        if entry_id is None:
            return
        if chosen is edit:
            self.edit_requested.emit(entry_id)
        elif chosen is favorite:
            self.favorite_requested.emit(entry_id)
        elif chosen is archive:
            (self.restore_requested if self.archived else self.archive_requested).emit(entry_id)
        elif chosen is delete:
            self.delete_requested.emit(entry_id)

    def _remember_sort(self, column: int, order: Qt.SortOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        scope = "archive" if self.archived else "active"
        self.settings.setValue(f"journal/sort/{scope}/column", int(column))
        self.settings.setValue(f"journal/sort/{scope}/order", int(order))
        self.settings.sync()
        self._save_header_state()

    def refresh_reference_filters(self, refresh: bool = True) -> None:
        old_category = self.category_combo.currentData() if hasattr(self, "category_combo") else None
        old_person = self.person_combo.currentData() if hasattr(self, "person_combo") else None
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(True)
            self.category_combo.clear()
            self.category_combo.addItem("همه دسته‌بندی‌ها", None)
            for category in self.repository.categories():
                self.category_combo.addItem(category["name"], category["id"])
            index = self.category_combo.findData(old_category)
            self.category_combo.setCurrentIndex(index if index >= 0 else 0)
            self.category_combo.blockSignals(False)
            fit_combo_to_contents(self.category_combo, maximum_width=230)
        if hasattr(self, "person_combo"):
            self.person_combo.blockSignals(True)
            self.person_combo.clear()
            self.person_combo.addItem("همه اشخاص", None)
            for person in self.repository.people():
                self.person_combo.addItem(person["name"], person["id"])
            index = self.person_combo.findData(old_person)
            self.person_combo.setCurrentIndex(index if index >= 0 else 0)
            self.person_combo.blockSignals(False)
            fit_combo_to_contents(self.person_combo, maximum_width=230)
        if hasattr(self, "tags_filter_list"):
            selected_tag_ids = {
                int(self.tags_filter_list.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.tags_filter_list.count())
                if self.tags_filter_list.item(i).checkState() == Qt.CheckState.Checked
            }
            self.tags_filter_list.blockSignals(True)
            self.tags_filter_list.clear()
            for tag in self.repository.tags():
                item = QListWidgetItem(f"#  {tag['name']}")
                item.setData(Qt.ItemDataRole.UserRole, int(tag["id"]))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setCheckState(Qt.CheckState.Checked if int(tag["id"]) in selected_tag_ids else Qt.CheckState.Unchecked)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor(tag.get("color") or "#38BDF8"))
                self.tags_filter_list.addItem(item)
            self.tags_filter_list.blockSignals(False)
        if refresh and hasattr(self, "table"):
            self.refresh()

    def _selected_filter_tag_ids(self) -> list[int]:
        return [
            int(self.tags_filter_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.tags_filter_list.count())
            if self.tags_filter_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _set_advanced_search_visible(self, visible: bool) -> None:
        """Expand the advanced filter panel without letting its children collapse vertically."""
        self.advanced_panel.setVisible(bool(visible))
        if visible:
            for widget in (self.date_from_edit, self.date_to_edit, self.importance_filter_combo, self.follow_up_filter_combo):
                widget.setMinimumHeight(44)
            self.advanced_panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            for widget in self.advanced_panel.findChildren(QLabel):
                if not widget.property("navaPreserveCenter"):
                    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                    widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for combo in self.advanced_panel.findChildren(QComboBox):
                combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.advanced_panel.ensurePolished()
            self.advanced_panel.updateGeometry()
            if self.advanced_panel.layout() is not None:
                self.advanced_panel.layout().activate()
            self.updateGeometry()

    def _clear_advanced_filters(self) -> None:
        self.date_from_edit.clear()
        self.date_to_edit.clear()
        self.tags_filter_list.blockSignals(True)
        for index in range(self.tags_filter_list.count()):
            self.tags_filter_list.item(index).setCheckState(Qt.CheckState.Unchecked)
        self.tags_filter_list.blockSignals(False)
        self.advanced_error.clear()
        self.advanced_error.hide()
        self.importance_filter_combo.setCurrentIndex(0)
        self.follow_up_filter_combo.setCurrentIndex(0)
        self.refresh()

    @staticmethod
    def _compact_jalali_to_iso(value: str) -> str | None:
        clean = to_en_digits(value.strip()).replace("/", ".").replace("-", ".")
        if not clean:
            return None
        pieces = [part.strip() for part in clean.split(".")]
        if len(pieces) != 3 or not all(part.isdigit() for part in pieces):
            raise ValueError("تاریخ را به شکل YY.MM.DD وارد کن؛ مثال: 05.08.07")
        year, month, day = (int(part) for part in pieces)
        if len(pieces[0]) <= 2:
            year = (current_jalali().year // 100) * 100 + year
        if year < 1:
            raise ValueError("سال واردشده معتبر نیست.")
        return iso_from_jalali(year, month, day)

    def selected_entry_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value else None

    def _edit_selected_row(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item:
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                self.edit_requested.emit(int(value))

    def _table_cell_clicked(self, row: int, column: int) -> None:
        if column == 10:
            item = self.table.item(row, 0)
            if item:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value:
                    self.favorite_requested.emit(int(value))

    def _edit_current(self) -> None:
        entry_id = self.selected_entry_id()
        if entry_id is not None:
            self.edit_requested.emit(entry_id)
        else:
            show_info(self, "انتخاب رویداد", "ابتدا یک رویداد را انتخاب کن.")

    def _delete_current(self) -> None:
        entry_id = self.selected_entry_id()
        if entry_id is not None:
            self.delete_requested.emit(entry_id)
        else:
            show_info(self, "انتخاب رویداد", "ابتدا یک رویداد را انتخاب کن.")

    def _archive_current(self) -> None:
        entry_id = self.selected_entry_id()
        if entry_id is None:
            show_info(self, "انتخاب رویداد", "ابتدا یک رویداد را انتخاب کن.")
            return
        (self.restore_requested if self.archived else self.archive_requested).emit(entry_id)

    def refresh(self) -> None:
        try:
            date_from = self._compact_jalali_to_iso(self.date_from_edit.text())
            date_to = self._compact_jalali_to_iso(self.date_to_edit.text())
            if date_from and date_to and date_from > date_to:
                raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد.")
        except ValueError as exc:
            self.advanced_error.setText(str(exc))
            self.advanced_error.show()
            return
        self.advanced_error.clear()
        self.advanced_error.hide()
        entries = self.repository.list_entries(
            query=self.search_edit.text(),
            category_id=self.category_combo.currentData(),
            person_id=self.person_combo.currentData(),
            favorites_only=self.favorite_check.isChecked(),
            archived=self.archived,
            tag_ids=self._selected_filter_tag_ids(),
            date_from=date_from,
            date_to=date_to,
            importance=self.importance_filter_combo.currentData(),
            follow_up_status=self.follow_up_filter_combo.currentData(),
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            entry_id = int(entry["id"])
            title = entry["title"]
            if entry["is_favorite"]:
                title = "✦  " + title
            date_item = _sort_item(display_digits(format_jalali(entry["event_date"])), jalali_sort_key(entry["event_date"]), entry_id)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            date_item.setData(CENTERED_ROLE, True)
            self.table.setItem(row, 0, date_item)
            self.table.setItem(row, 1, _sort_item(title, entry["title"].casefold(), entry_id))
            category_item = _sort_item(entry["category_name"] or "—", (entry["category_name"] or "").casefold(), entry_id)
            if entry.get("category_color"):
                category_item.setForeground(QColor(entry["category_color"]))
            self.table.setItem(row, 2, category_item)
            person_item = _sort_item(entry["person_name"] or "—", (entry["person_name"] or "").casefold(), entry_id)
            if entry.get("person_color"):
                person_item.setForeground(QColor(entry["person_color"]))
            self.table.setItem(row, 3, person_item)
            follow_up_value = str(entry.get("follow_up_status") or "none")
            follow_up_text = FOLLOW_UP_LABELS.get(follow_up_value, follow_up_value)
            follow_up_item = _sort_item(follow_up_text, follow_up_value, entry_id)
            follow_up_item.setForeground(QColor(theme_follow_up_color(follow_up_value)))
            self.table.setItem(row, 4, follow_up_item)
            importance_value = str(entry.get("importance") or "normal")
            importance_text = IMPORTANCE_LABELS.get(importance_value, importance_value)
            importance_item = _sort_item(importance_text, importance_value, entry_id)
            importance_item.setForeground(QColor(theme_importance_color(importance_value)))
            self.table.setItem(row, 5, importance_item)
            tags_text = entry.get("tag_names") or ""
            tag_display = "  ".join(f"#{tag.strip()}" for tag in tags_text.split("،") if tag.strip()) or "—"
            tag_item = _sort_item(tag_display, tags_text.casefold(), entry_id)
            tag_item.setForeground(QColor(semantic_color("tag")))
            self.table.setItem(row, 6, tag_item)
            attachment_item = _sort_item(display_digits(entry["attachment_count"]), int(entry["attachment_count"]), entry_id)
            attachment_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            attachment_item.setData(CENTERED_ROLE, True)
            self.table.setItem(row, 7, attachment_item)
            created_text = display_digits(format_timestamp(entry["created_at"]))
            created_item = _sort_item(created_text, entry["created_at"], entry_id)
            created_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            created_item.setData(CENTERED_ROLE, True)
            self.table.setItem(row, 8, created_item)
            updated_item = _sort_item(display_digits(format_timestamp(entry["updated_at"])), entry["updated_at"], entry_id)
            updated_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            updated_item.setData(CENTERED_ROLE, True)
            self.table.setItem(row, 9, updated_item)
            star = _sort_item("★" if entry["is_favorite"] else "☆", int(entry["is_favorite"]), entry_id)
            star.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            star.setData(CENTERED_ROLE, True)
            app = QApplication.instance()
            star.setFont(QFont("Segoe UI Symbol", 10))
            star.setForeground(QColor(semantic_color("favorite") if entry["is_favorite"] else semantic_color("normal")))
            star.setToolTip("برای تغییر علاقه‌مندی کلیک کن؛ برای مرتب‌سازی سرستون را بزن")
            self.table.setItem(row, 10, star)
        self.table.setSortingEnabled(True)
        self.table.sortItems(self._sort_column, self._sort_order)
        self.count_label.setText(f"{display_digits(len(entries))} رویداد")
        self.table.clearSelection()


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    background_highlight_changed = Signal(str)
    demo_data_seed_requested = Signal()
    demo_data_clear_requested = Signal()
    font_changed = Signal(str)
    numeric_font_changed = Signal(str)
    font_size_changed = Signal(int)
    avatar_changed = Signal(str)
    ui_preferences_changed = Signal(str, str, str, str)
    backup_requested = Signal()
    open_data_folder_requested = Signal()
    export_requested = Signal()
    integrity_requested = Signal()
    update_requested = Signal(str)
    database_path_change_requested = Signal(str, bool)

    def __init__(
        self, database, theme: str = "dark", install_root=None, app_version: str = APP_VERSION, settings=None
    ) -> None:
        super().__init__()
        from pathlib import Path
        root_path = Path(install_root) if install_root else Path(__file__).resolve().parent.parent
        self.database = database
        self.settings = settings
        self.app_version = app_version
        self.update_manager = UpdateManager(root_path, database.app_data_dir, app_version)
        self.selected_update_path: str | None = None
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content_widget = QWidget()
        content_widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        outer = QVBoxLayout(content_widget)
        outer.setContentsMargins(28, 25, 28, 22)
        outer.setSpacing(18)
        outer.addLayout(make_page_header("تنظیمات و نگهداری", "ظاهر برنامه، به‌روزرسانی جزئی، پشتیبان‌گیری و سلامت پایگاه داده را مدیریت کن."))
        self.scroll_area.setWidget(content_widget)
        root_layout.addWidget(self.scroll_area)

        appearance = QFrame()
        appearance.setObjectName("settingsCard")
        a = QVBoxLayout(appearance)
        a.setContentsMargins(20, 18, 20, 18)
        a.setSpacing(12)
        label = QLabel("ظاهر برنامه")
        label.setObjectName("sectionTitle")
        description = QLabel("پوسته، فونت، جهت چیدمان و تراز متن هرکدام مستقل تنظیم می‌شوند. تنظیم‌ها برای اجراهای بعدی هم ذخیره خواهند شد.")
        description.setObjectName("muted")
        description.setWordWrap(True)
        self.theme_combo = NoWheelComboBox()
        self.theme_combo.addItem("تیرهٔ نئونی · Glass", "dark")
        self.theme_combo.addItem("روشن مینیمال · Minimal", "light")
        self.theme_combo.addItem("فضای کاری مدرن · Linear", "linear")
        idx = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._emit_theme)

        highlight_label = QLabel("هایلایت لطیف پس‌زمینه")
        highlight_label.setObjectName("fieldLabel")
        highlight_help = QLabel("یک هالهٔ رنگی بسیار ملایم روی فضای اصلی برنامه؛ کارت‌ها، پنجره‌ها و فهرست‌های باز مات می‌مانند.")
        highlight_help.setObjectName("muted")
        highlight_help.setWordWrap(True)
        self.background_highlight_combo = NoWheelComboBox()
        self.background_highlight_combo.addItem("نعنایی آرام", "mint")
        self.background_highlight_combo.addItem("آبی مه‌آلود", "blue")
        self.background_highlight_combo.addItem("بنفش ملایم", "violet")
        self.background_highlight_combo.addItem("کهربایی لطیف", "amber")
        self.background_highlight_combo.addItem("رز غبارآلود", "rose")
        self.background_highlight_combo.addItem("یخی روشن", "ice")
        self.background_highlight_combo.addItem("بدون هایلایت", "none")
        saved_highlight = settings.value("appearance/background_highlight", "mint", type=str) if settings is not None else "mint"
        highlight_index = self.background_highlight_combo.findData(saved_highlight)
        self.background_highlight_combo.setCurrentIndex(highlight_index if highlight_index >= 0 else 0)
        self.background_highlight_combo.currentIndexChanged.connect(self._emit_background_highlight)

        font_label = QLabel("فونت رابط کاربری")
        font_label.setObjectName("fieldLabel")
        self.font_combo = NoWheelComboBox()
        self.font_combo.addItem("انتخاب خودکار فونت فارسی", "auto")
        try:
            installed_fonts = {name.casefold(): name for name in QFontDatabase().families()}
        except Exception:
            installed_fonts = {}
        preferred_fonts = ("Vazirmatn UI", "Vazirmatn", "IRANSansX", "IRANSans", "Shabnam", "Sahel", "Noto Sans Arabic", "Segoe UI", "Tahoma")
        for family in preferred_fonts:
            actual = installed_fonts.get(family.casefold())
            if actual and self.font_combo.findData(actual) < 0:
                self.font_combo.addItem(actual, actual)
        self.font_combo.insertSeparator(self.font_combo.count())
        for actual in sorted(installed_fonts.values(), key=str.casefold):
            if self.font_combo.findData(actual) < 0:
                self.font_combo.addItem(actual, actual)
        self.font_combo.setMaxVisibleItems(24)
        saved_font = settings.value("appearance/font", "auto", type=str) if settings is not None else "auto"
        font_index = self.font_combo.findData(saved_font)
        self.font_combo.setCurrentIndex(font_index if font_index >= 0 else 0)
        self.font_combo.currentIndexChanged.connect(self._emit_font)

        # The font-size setting is a self-contained RTL block. A dedicated host
        # makes its physical right anchoring independent from the app-wide layout preference.
        font_size_panel = QWidget()
        font_size_panel.setObjectName("globalFontSizePanel")
        # Physical placement is LTR; right alignment is applied locally to the Persian
        # labels and the combo's contents. This avoids double-mirroring in RTL parents.
        font_size_panel.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        font_size_panel.setProperty("navaPreserveLayoutDirection", True)
        font_size_panel.setMinimumWidth(0)
        font_size_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        font_size_panel_layout = QVBoxLayout(font_size_panel)
        font_size_panel_layout.setContentsMargins(0, 0, 0, 0)
        font_size_panel_layout.setSpacing(5)

        font_size_title = QLabel("اندازه فونت کل برنامه")
        font_size_title.setObjectName("fieldLabel")
        font_size_title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        font_size_title.setMinimumWidth(0)
        font_size_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        font_size_title.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        font_size_title.setProperty("navaPreserveAlignment", True)
        font_size_title.setProperty("navaPreserveLayoutDirection", True)
        font_size_title_row_host = QWidget(font_size_panel)
        font_size_title_row_host.setObjectName("globalFontSizeTitleRowHost")
        font_size_title_row_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        font_size_title_row_host.setProperty("navaPreserveLayoutDirection", True)
        font_size_title_row = QHBoxLayout(font_size_title_row_host)
        font_size_title_row.setContentsMargins(0, 0, 0, 0)
        font_size_title_row.setSpacing(0)
        font_size_title_row.setDirection(QBoxLayout.Direction.LeftToRight)
        font_size_title_row.addStretch(1)
        font_size_title_row.addWidget(font_size_title, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.font_size_combo = NoWheelComboBox()
        self.font_size_combo.setObjectName("globalFontSizeCombo")
        self.font_size_combo.setMinimumWidth(116)
        self.font_size_combo.setMaximumWidth(156)
        self.font_size_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.font_size_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.font_size_combo.setProperty("navaPreserveLayoutDirection", True)
        self.font_size_combo.setProperty("navaPreserveAlignment", True)
        for size in range(8, 19):
            self.font_size_combo.addItem(f"{size} pt", size)
        for index in range(self.font_size_combo.count()):
            model_item = self.font_size_combo.model().item(index)
            if model_item is not None:
                model_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        saved_size = settings.value("appearance/font_size", 10, type=int) if settings is not None else 10
        size_index = self.font_size_combo.findData(max(8, min(18, int(saved_size))))
        self.font_size_combo.setCurrentIndex(size_index if size_index >= 0 else self.font_size_combo.findData(10))
        self.font_size_combo.currentIndexChanged.connect(self._commit_font_size)

        font_size_row_host = QWidget(font_size_panel)
        font_size_row_host.setObjectName("globalFontSizeRowHost")
        font_size_row_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        font_size_row_host.setProperty("navaPreserveLayoutDirection", True)
        font_size_row = QHBoxLayout(font_size_row_host)
        font_size_row.setDirection(QBoxLayout.Direction.LeftToRight)
        font_size_row.setContentsMargins(0, 0, 0, 0)
        # LTR physical row: stretch first, control last => combo stays at the right edge.
        font_size_row.addStretch(1)
        font_size_row.addWidget(self.font_size_combo, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # The explanatory hint was removed at the user's request; keep the
        # font title and numeric selector only to avoid a redundant RTL-sensitive line.
        font_size_panel_layout.addWidget(font_size_title_row_host)
        font_size_panel_layout.addWidget(font_size_row_host)
        self._font_size_panel = font_size_panel
        self._font_size_row_host = font_size_row_host
        self._font_size_row_layout = font_size_row
        self._font_size_title_row_host = font_size_title_row_host
        self._font_size_title_row_layout = font_size_title_row
        self._font_size_title = font_size_title

        # Avatar selection is a user preference; the selected image is displayed
        # in the application brand mark and remains independent of the database.
        avatar_title = QLabel("تصویر آواتار برنامه")
        avatar_title.setObjectName("fieldLabel")
        avatar_row = QHBoxLayout()
        avatar_row.setDirection(QBoxLayout.Direction.RightToLeft)
        avatar_row.setSpacing(12)
        self.avatar_preview = QLabel("ن")
        self.avatar_preview.setObjectName("settingsAvatarPreview")
        self.avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_preview.setFixedSize(54, 54)
        self.avatar_preview.setProperty("navaPreserveCenter", True)
        self.avatar_path_label = QLabel("بدون تصویر آواتار")
        self.avatar_path_label.setObjectName("muted")
        self.avatar_path_label.setWordWrap(True)
        self.choose_avatar_button = QPushButton("انتخاب تصویر…")
        self.choose_avatar_button.setProperty("compact", True)
        self.clear_avatar_button = QPushButton("حذف تصویر")
        self.clear_avatar_button.setProperty("compact", True)
        avatar_actions = QVBoxLayout()
        avatar_actions.setSpacing(6)
        avatar_actions.addWidget(self.choose_avatar_button)
        avatar_actions.addWidget(self.clear_avatar_button)
        avatar_row.addWidget(self.avatar_preview)
        avatar_row.addWidget(self.avatar_path_label, 1)
        avatar_row.addLayout(avatar_actions)
        self._display_avatar_preview(str(settings.value("profile/avatar_path", "", type=str)) if settings is not None else "")
        self.choose_avatar_button.clicked.connect(self._choose_avatar)
        self.clear_avatar_button.clicked.connect(self._clear_avatar)

        numeric_font_label = QLabel("فونت متن و اعداد جدول ژورنال")
        numeric_font_label.setObjectName("fieldLabel")
        self.numeric_font_combo = NoWheelComboBox()
        self.numeric_font_combo.addItem("همان فونت رابط کاربری", "same")
        numeric_candidates = (
            "Vazirmatn UI", "Vazirmatn", "IRANSansX", "IRANSans", "Shabnam", "Sahel",
            "Noto Sans Arabic", "Segoe UI", "Segoe UI Variable", "Arial", "Tahoma", "Consolas",
        )
        for family in numeric_candidates:
            actual = installed_fonts.get(family.casefold())
            if actual and self.numeric_font_combo.findData(actual) < 0:
                self.numeric_font_combo.addItem(actual, actual)
        self.numeric_font_combo.insertSeparator(self.numeric_font_combo.count())
        for actual in sorted(installed_fonts.values(), key=str.casefold):
            if self.numeric_font_combo.findData(actual) < 0:
                self.numeric_font_combo.addItem(actual, actual)
        self.numeric_font_combo.setMaxVisibleItems(24)
        saved_numeric_font = settings.value("appearance/numeric_font", "same", type=str) if settings is not None else "same"
        numeric_index = self.numeric_font_combo.findData(saved_numeric_font)
        self.numeric_font_combo.setCurrentIndex(numeric_index if numeric_index >= 0 else 0)
        self.numeric_font_combo.currentIndexChanged.connect(self._emit_numeric_font)

        direction_label = QLabel("جهت چیدمان رابط")
        direction_label.setObjectName("fieldLabel")
        self.layout_direction_combo = NoWheelComboBox()
        self.layout_direction_combo.addItem("راست‌به‌چپ · RTL", "rtl")
        self.layout_direction_combo.addItem("چپ‌به‌راست · LTR", "ltr")
        saved_direction = settings.value("appearance/layout_direction", "rtl", type=str) if settings is not None else "rtl"
        direction_index = self.layout_direction_combo.findData(saved_direction)
        self.layout_direction_combo.setCurrentIndex(direction_index if direction_index >= 0 else 0)

        alignment_label = QLabel("تراز متن فیلدها و نوشته‌ها")
        alignment_label.setObjectName("fieldLabel")
        self.text_alignment_combo = NoWheelComboBox()
        self.text_alignment_combo.addItem("راست‌چین · Align Right", "right")
        self.text_alignment_combo.addItem("چپ‌چین · Align Left", "left")
        self.text_alignment_combo.addItem("ابتدای خط · Start", "start")
        self.text_alignment_combo.addItem("وسط‌چین · Center", "center")
        saved_alignment = settings.value("appearance/text_alignment", "right", type=str) if settings is not None else "right"
        alignment_index = self.text_alignment_combo.findData(saved_alignment)
        self.text_alignment_combo.setCurrentIndex(alignment_index if alignment_index >= 0 else 0)

        table_alignment_label = QLabel("تراز مستقل ستون‌های ژورنال")
        table_alignment_label.setObjectName("fieldLabel")
        self.table_alignment_combo = NoWheelComboBox()
        self.table_alignment_combo.addItem("مطابق تراز عمومی", "auto")
        self.table_alignment_combo.addItem("راست‌چین جدول", "right")
        self.table_alignment_combo.addItem("چپ‌چین جدول", "left")
        self.table_alignment_combo.addItem("وسط‌چین جدول", "center")
        saved_table_alignment = settings.value("appearance/table_alignment", "auto", type=str) if settings is not None else "auto"
        table_alignment_index = self.table_alignment_combo.findData(saved_table_alignment)
        self.table_alignment_combo.setCurrentIndex(table_alignment_index if table_alignment_index >= 0 else 0)

        digits_label = QLabel("شکل اعداد در ژورنال و داشبورد")
        digits_label.setObjectName("fieldLabel")
        self.digits_combo = NoWheelComboBox()
        self.digits_combo.addItem("لاتین · 0123456789", "latin")
        self.digits_combo.addItem("فارسی · ۰۱۲۳۴۵۶۷۸۹", "persian")
        saved_digits = settings.value("appearance/digit_mode", "latin", type=str) if settings is not None else "latin"
        digits_index = self.digits_combo.findData(saved_digits)
        self.digits_combo.setCurrentIndex(digits_index if digits_index >= 0 else 0)

        preference_note = QLabel("برای عیب‌یابی راست‌چینی، جهت چیدمان، تراز متن عمومی و تراز جدول را جداگانه تغییر بده. فونت متن/اعداد و شکل رقم‌ها هم مستقل‌اند؛ برای مثال 05.08.07 یا ۰۵.۰۸.۰۷.")
        preference_note.setObjectName("muted")
        preference_note.setWordWrap(True)
        self.reset_ui_button = QPushButton("بازنشانی جهت، تراز، فونت و اندازه")
        self.reset_ui_button.setProperty("compact", True)
        self.layout_direction_combo.currentIndexChanged.connect(self._emit_ui_preferences)
        self.text_alignment_combo.currentIndexChanged.connect(self._emit_ui_preferences)
        self.digits_combo.currentIndexChanged.connect(self._emit_ui_preferences)
        self.table_alignment_combo.currentIndexChanged.connect(self._emit_ui_preferences)
        self.reset_ui_button.clicked.connect(self._reset_ui_preferences)

        a.addWidget(label)
        a.addWidget(description)
        a.addWidget(avatar_title)
        a.addLayout(avatar_row)
        a.addWidget(self.theme_combo)
        a.addWidget(highlight_label)
        a.addWidget(self.background_highlight_combo)
        a.addWidget(highlight_help)
        a.addWidget(font_label)
        a.addWidget(self.font_combo)
        a.addWidget(font_size_panel)
        a.addWidget(numeric_font_label)
        a.addWidget(self.numeric_font_combo)
        a.addWidget(direction_label)
        a.addWidget(self.layout_direction_combo)
        a.addWidget(alignment_label)
        a.addWidget(self.text_alignment_combo)
        a.addWidget(table_alignment_label)
        a.addWidget(self.table_alignment_combo)
        a.addWidget(digits_label)
        a.addWidget(self.digits_combo)
        a.addWidget(preference_note)
        a.addWidget(self.reset_ui_button, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(appearance)

        update_card = QFrame()
        update_card.setObjectName("updateCard")
        u = QVBoxLayout(update_card)
        u.setContentsMargins(20, 18, 20, 18)
        u.setSpacing(11)
        update_title = QLabel("به‌روزرسانی هوشمند از فایل ZIP")
        update_title.setObjectName("sectionTitle")
        update_description = QLabel(
            "یک بسته به‌روزرسانی جزئی انتخاب کن. برنامه نسخه پایه و هش فایل‌ها را بررسی می‌کند، از پایگاه داده پشتیبان می‌گیرد، "
            "فقط فایل‌های اعلام‌شده در بسته را جایگزین می‌کند و سپس خودش بسته و دوباره اجرا می‌شود. "
            "فایل‌های شخصی و خود پایگاه داده هرگز مقصد به‌روزرسانی نیستند."
        )
        update_description.setWordWrap(True)
        update_description.setObjectName("muted")
        self.version_label = QLabel(f"نسخه فعلی روزنگار: {app_version}")
        self.version_label.setObjectName("updateVersion")
        pick_row = QHBoxLayout()
        self.choose_update_button = QPushButton("انتخاب فایل ZIP به‌روزرسانی")
        self.choose_update_button.setProperty("primary", True)
        self.apply_update_button = QPushButton("اعمال و راه‌اندازی مجدد")
        self.apply_update_button.setEnabled(False)
        pick_row.addWidget(self.choose_update_button)
        pick_row.addWidget(self.apply_update_button)
        pick_row.addStretch(1)
        self.patch_summary = QLabel("هنوز بسته‌ای انتخاب نشده است.\nبرای نسخه فعلی، بسته باید در manifest نسخه پایه دقیقاً برابر با همین نسخه داشته باشد.")
        self.patch_summary.setWordWrap(True)
        self.patch_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.patch_summary.setObjectName("muted")
        self.update_timeline = QListWidget()
        self.update_timeline.setObjectName("updateTimeline")
        self.update_timeline.setMaximumHeight(154)
        for heading, detail in (
            ("۱ · اعتبارسنجی", "نسخه پایه، مسیرها، اندازه و SHA-256 همه فایل‌های بسته بررسی می‌شود."),
            ("۲ · پشتیبان امن", "یک کپی مستقل از SQLite پیش از اعمال تغییرات ساخته می‌شود."),
            ("۳ · جایگزینی جزئی", "فقط فایل‌های فهرست‌شده در manifest تغییر می‌کنند؛ فایل‌های دیگر لمس نمی‌شوند."),
            ("۴ · راه‌اندازی مجدد", "عامل جداگانه بعد از خروج برنامه فایل‌ها را اعمال و روزنگار را دوباره اجرا می‌کند."),
        ):
            item = QListWidgetItem(f"{heading}\n    {detail}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.update_timeline.addItem(item)
        self.update_history_label = QLabel("")
        self.update_history_label.setWordWrap(True)
        self.update_history_label.setObjectName("updateStatus")
        self.update_history_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        u.addWidget(update_title)
        u.addWidget(update_description)
        u.addWidget(self.version_label)
        u.addLayout(pick_row)
        u.addWidget(self.patch_summary)
        u.addWidget(self.update_timeline)
        u.addWidget(self.update_history_label)
        outer.addWidget(update_card)
        self._show_last_update_status()
        self.choose_update_button.clicked.connect(self._choose_update_zip)
        self.apply_update_button.clicked.connect(self._emit_update_request)

        storage = QFrame()
        storage.setObjectName("settingsCard")
        s = QVBoxLayout(storage)
        s.setContentsMargins(20, 18, 20, 18)
        s.setSpacing(12)
        s_title = QLabel("پایگاه داده و پشتیبان‌گیری")
        s_title.setObjectName("sectionTitle")
        self.storage_path_label = QLabel("مسیر کامل فایل پایگاه داده فعال")
        self.storage_path_label.setObjectName("muted")
        self.storage_path_value = QLabel("")
        self.storage_path_value.setObjectName("databasePathValue")
        self.storage_path_value.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.storage_path_value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.storage_path_value.setWordWrap(True)
        self.storage_path_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.storage_path_value.setProperty("navaPreserveLayoutDirection", True)
        self.storage_path_value.setProperty("navaPreserveAlignment", True)
        storage_path_hint = QLabel("مسیر پشتیبان و گزارش به‌روزرسانی جدا از فایل اصلی نگهداری می‌شود.")
        storage_path_hint.setObjectName("muted")
        storage_path_hint.setWordWrap(True)
        auto_backup_label = QLabel("پشتیبان خودکار هنگام بستن برنامه")
        auto_backup_label.setObjectName("fieldLabel")
        self.auto_backup_path_value = QLabel(str(preferred_backup_folder(root_path)))
        self.auto_backup_path_value.setObjectName("databasePathValue")
        self.auto_backup_path_value.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.auto_backup_path_value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.auto_backup_path_value.setWordWrap(True)
        self.auto_backup_path_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.auto_backup_path_value.setProperty("navaPreserveLayoutDirection", True)
        self.auto_backup_path_value.setProperty("navaPreserveAlignment", True)
        auto_backup_hint = QLabel("هر بار بستن روزنگار، یک فایل مستقل با تاریخ و ساعت شمسی ساخته می‌شود؛ فایل اصلی و نسخه‌های قبلی تغییر یا حذف نمی‌شوند. اگر پوشه برنامه قابل نوشتن نباشد، از پوشه داده‌های محلی کاربر استفاده می‌شود.")
        auto_backup_hint.setObjectName("muted")
        auto_backup_hint.setWordWrap(True)
        s.addWidget(s_title)
        s.addWidget(QLabel(f"SQLite · نسخه ساختار {database.schema_version()}"))
        s.addWidget(self.storage_path_label)
        s.addWidget(self.storage_path_value)
        s.addWidget(storage_path_hint)
        s.addWidget(auto_backup_label)
        s.addWidget(self.auto_backup_path_value)
        s.addWidget(auto_backup_hint)
        path_row = QHBoxLayout()
        path_row.setDirection(QBoxLayout.Direction.RightToLeft)
        self.change_data_path_button = QPushButton("انتقال پایگاه داده به مسیر جدید…")
        self.change_data_path_button.setProperty("primary", True)
        self.open_current_path_button = QPushButton("بازکردن محل فعلی")
        path_row.addWidget(self.change_data_path_button)
        path_row.addWidget(self.open_current_path_button)
        path_row.addStretch(1)
        s.addLayout(path_row)
        self.change_data_path_button.clicked.connect(self._choose_data_path)
        self.open_current_path_button.clicked.connect(self.open_data_folder_requested.emit)
        self.set_database_path(database.path)
        button_row = QHBoxLayout()
        self.backup_button = QPushButton("⇩  ساخت نسخه پشتیبان")
        self.backup_button.setProperty("primary", True)
        self.folder_button = QPushButton("بازکردن پوشه داده‌ها")
        self.export_button = QPushButton("خروجی CSV")
        self.check_button = QPushButton("بررسی سلامت پایگاه داده")
        button_row.addWidget(self.backup_button)
        button_row.addWidget(self.folder_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.check_button)
        s.addLayout(button_row)
        outer.addWidget(storage)

        architecture = QFrame()
        architecture.setObjectName("settingsCard")
        ar = QVBoxLayout(architecture)
        ar.setContentsMargins(20, 18, 20, 18)
        ar.setSpacing(8)
        arch_title = QLabel("معماری قابل توسعه")
        arch_title.setObjectName("sectionTitle")
        arch_body = QLabel(
            "رابط کاربری، منطق ثبت و لایه داده از هم جدا هستند. به‌روزرسانی‌ها به‌صورت بسته‌های تفاضلی شامل فقط فایل‌های تغییرکرده توزیع می‌شوند. "
            "ساختار دیتابیس نسخه‌بندی‌شده است و تغییرات آینده باید با مهاجرت افزایشی اعمال شوند.\n\n"
            "نکته: فایل‌های پیوست در مسیر اصلی خود باقی می‌مانند؛ برنامه فقط مسیر آن‌ها را به رویداد وصل می‌کند."
        )
        arch_body.setWordWrap(True)
        arch_body.setObjectName("muted")
        ar.addWidget(arch_title)
        ar.addWidget(arch_body)
        outer.addWidget(architecture)
        outer.addStretch(1)

        self.backup_button.clicked.connect(self.backup_requested.emit)
        self.folder_button.clicked.connect(self.open_data_folder_requested.emit)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.check_button.clicked.connect(self.integrity_requested.emit)

        demo_card = QFrame()
        demo_card.setObjectName("settingsCard")
        demo_layout = QVBoxLayout(demo_card)
        demo_layout.setContentsMargins(20, 18, 20, 18)
        demo_layout.setSpacing(9)
        demo_title = QLabel("دادهٔ آزمایشی برای بررسی کامل برنامه")
        demo_title.setObjectName("sectionTitle")
        demo_description = QLabel(
            "۵۰ رویداد ساختگی با تاریخ‌های پراکنده در دو سال گذشته، دسته‌بندی، اشخاص، برچسب، اهمیت، وضعیت پیگیری، "
            "علاقه‌مندی، بایگانی و چند فایل پیوست نمونه به همین پایگاه داده افزوده می‌شود. اطلاعات واقعی تو دست‌نخورده می‌ماند "
            "و با دکمهٔ حذف می‌توان فقط همین بستهٔ آزمایشی را پاک کرد."
        )
        demo_description.setObjectName("muted")
        demo_description.setWordWrap(True)
        demo_button_row = QHBoxLayout()
        demo_button_row.setDirection(QBoxLayout.Direction.RightToLeft)
        self.seed_demo_data_button = QPushButton("＋ افزودن ۵۰ رکورد آزمایشی")
        self.seed_demo_data_button.setProperty("primary", True)
        self.clear_demo_data_button = QPushButton("حذف رکوردهای آزمایشی")
        self.clear_demo_data_button.setProperty("danger", True)
        demo_button_row.addWidget(self.seed_demo_data_button)
        demo_button_row.addWidget(self.clear_demo_data_button)
        demo_button_row.addStretch(1)
        self.seed_demo_data_button.clicked.connect(self.demo_data_seed_requested.emit)
        self.clear_demo_data_button.clicked.connect(self.demo_data_clear_requested.emit)
        demo_layout.addWidget(demo_title)
        demo_layout.addWidget(demo_description)
        demo_layout.addLayout(demo_button_row)
        outer.addWidget(demo_card)

        apply_rtl(self)
        self.enforce_font_size_layout()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Pin the font-size control block after the settings page becomes visible."""
        super().showEvent(event)
        self.enforce_font_size_layout()
        QTimer.singleShot(0, self.enforce_font_size_layout)

    def enforce_font_size_layout(self) -> None:
        """Keep the font-size title and dropdown physically right-aligned."""
        rtl = Qt.LayoutDirection.RightToLeft
        ltr = Qt.LayoutDirection.LeftToRight
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        # Parent and row direction control physical placement; Persian text direction is local.
        for widget in (
            getattr(self, "_font_size_panel", None),
            getattr(self, "_font_size_row_host", None),
            getattr(self, "_font_size_title_row_host", None),
        ):
            if widget is not None:
                widget.setLayoutDirection(ltr)
                widget.setProperty("navaPreserveLayoutDirection", True)
        for layout_name in ("_font_size_title_row_layout",):
            text_row = getattr(self, layout_name, None)
            if text_row is not None:
                text_row.setDirection(QBoxLayout.Direction.LeftToRight)
        row = getattr(self, "_font_size_row_layout", None)
        combo = getattr(self, "font_size_combo", None)
        if row is not None:
            row.setDirection(QBoxLayout.Direction.LeftToRight)
            # Rebuild order safely if a Qt relayout previously changed it.
            if combo is not None:
                row.removeWidget(combo)
                row.addWidget(combo, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.setAlignment(combo, right)
        if combo is not None:
            combo.setLayoutDirection(rtl)
            combo.setProperty("navaPreserveLayoutDirection", True)
            combo.setProperty("navaPreserveAlignment", True)
            model = combo.model()
            for index in range(combo.count()):
                try:
                    item = model.item(index)
                    if item is not None:
                        item.setTextAlignment(right)
                except AttributeError:
                    pass
        widget = getattr(self, "_font_size_title", None)
        if widget is not None:
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            widget.setLayoutDirection(rtl)
            widget.setAlignment(right)
            widget.setProperty("navaPreserveAlignment", True)
            widget.setProperty("navaPreserveLayoutDirection", True)

    def set_database_path(self, path: str | Path) -> None:
        self.storage_path_value.setText(str(path))
        self.storage_path_label.setToolTip(str(path))
        self.storage_path_value.setToolTip(str(path))

    def _choose_data_path(self) -> None:
        current = Path(self.database.path)
        suggested = str(current.parent / "NavaJournal_Data.sqlite3")
        destination, _ = QFileDialog.getSaveFileName(
            self, "انتخاب مقصد انتقال پایگاه داده", suggested,
            "SQLite database (*.sqlite3 *.sqlite *.db)",
        )
        if not destination:
            return
        path = Path(destination)
        if path.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
            path = path.with_suffix(".sqlite3")
        replace_existing = False
        if path.exists():
            if path.resolve() == current.resolve():
                show_info(self, "مسیر بدون تغییر", "این فایل هم‌اکنون پایگاه داده فعال است.")
                return
            answer = QMessageBox.question(
                self, "جایگزینی فایل مقصد",
                "فایل مقصد از قبل وجود دارد. اگر ادامه بدهی، فایل فعلی مقصد با نام زمان‌دار حفظ می‌شود و فایل پایگاه داده فعال به این مسیر منتقل خواهد شد. فایل اصلی پس از انتقال موفق از مسیر قبلی برداشته می‌شود. ادامه می‌دهی؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            replace_existing = True
        self.database_path_change_requested.emit(str(path), replace_existing)

    def _choose_update_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب بسته به‌روزرسانی روزنگار", "", "Nava Journal update (*.zip)")
        if not path:
            return
        try:
            manifest = self.update_manager.inspect_update(path)
        except UpdateError as exc:
            self.selected_update_path = None
            self.apply_update_button.setEnabled(False)
            self.patch_summary.setText(f"بسته پذیرفته نشد:\n{exc}")
            self.patch_summary.setObjectName("warningText")
            self.patch_summary.style().unpolish(self.patch_summary)
            self.patch_summary.style().polish(self.patch_summary)
            return
        self.selected_update_path = path
        self.apply_update_button.setEnabled(True)
        notes = manifest.get("release_notes") or ["در این بسته توضیحی ثبت نشده است."]
        files = "\n".join(f"  • {item['path']}" for item in manifest["files"])
        self.patch_summary.setObjectName("updateStatus")
        self.patch_summary.setText(
            f"بسته معتبر است · {manifest['base_version']}  →  {manifest['version']}\n"
            f"تعداد فایل‌های تغییرکرده: {len(manifest['files'])}\n"
            f"توضیحات انتشار: {'؛ '.join(str(note) for note in notes)}\n"
            f"فایل‌هایی که جایگزین می‌شوند:\n{files}"
        )
        self.patch_summary.style().unpolish(self.patch_summary)
        self.patch_summary.style().polish(self.patch_summary)

    def _emit_update_request(self) -> None:
        if self.selected_update_path:
            self.update_requested.emit(self.selected_update_path)

    def _show_last_update_status(self) -> None:
        status = self.update_manager.read_last_status()
        if not status:
            self.update_history_label.setText("گزارش به‌روزرسانی قبلی هنوز ثبت نشده است.")
            return
        state = status.get("state", "unknown")
        version = status.get("target_version", "—")
        if state in ("restarted", "completed"):
            heading = f"آخرین به‌روزرسانی موفق: نسخه {version}"
        elif state in ("failed", "restart_failed", "preparation_failed"):
            heading = f"آخرین به‌روزرسانی نیاز به بررسی دارد · نسخه هدف {version}"
        else:
            heading = f"آخرین وضعیت به‌روزرسانی: {state} · نسخه هدف {version}"
        events = status.get("timeline") or []
        details = "\n".join(f"{'✓' if event.get('state') in ('done', 'completed', 'restarted') else '•'} {event.get('title', '')}: {event.get('detail', '')}" for event in events[-6:])
        self.update_history_label.setText(heading + ("\n" + details if details else ""))

    def _display_avatar_preview(self, path: str) -> None:
        image_path = Path(path) if path else None
        if image_path is not None and image_path.is_file():
            source = QPixmap(str(image_path))
            if not source.isNull():
                size = self.avatar_preview.width()
                scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                x = max(0, (scaled.width() - size) // 2)
                y = max(0, (scaled.height() - size) // 2)
                cropped = scaled.copy(x, y, size, size)
                masked = QPixmap(size, size)
                masked.fill(Qt.GlobalColor.transparent)
                painter = QPainter(masked)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                path_clip = QPainterPath()
                path_clip.addRoundedRect(0, 0, size, size, 15, 15)
                painter.setClipPath(path_clip)
                painter.drawPixmap(0, 0, cropped)
                painter.end()
                self.avatar_preview.setPixmap(masked)
                self.avatar_preview.setText("")
                palette = theme_colors()
                self.avatar_preview.setStyleSheet(f"background:transparent; border:1px solid {palette['border']}; border-radius:15px;")
                self.avatar_path_label.setText(str(image_path))
                self.avatar_path_label.setToolTip(str(image_path))
                return
        self.avatar_preview.setPixmap(QPixmap())
        self.avatar_preview.setText("ن")
        palette = theme_colors()
        self.avatar_preview.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {palette['accent']},stop:1 {palette['success']}); "
            f"color:{contrast_foreground(palette['accent'])}; border:1px solid {palette['border']}; "
            "border-radius:16px; font-size:22pt; font-weight:800;"
        )
        self.avatar_path_label.setText("بدون تصویر آواتار؛ نشان پیش‌فرض روزنگار فعال است.")
        self.avatar_path_label.setToolTip("")

    def _choose_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب تصویر آواتار", "", "تصویرها (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if not path:
            return
        if QPixmap(path).isNull():
            show_info(self, "تصویر معتبر نیست", "فایل انتخاب‌شده به‌عنوان تصویر قابل‌خواندن نیست.")
            return
        if self.settings is not None:
            self.settings.setValue("profile/avatar_path", path)
            self.settings.sync()
        self._display_avatar_preview(path)
        self.avatar_changed.emit(path)

    def _clear_avatar(self) -> None:
        if self.settings is not None:
            self.settings.remove("profile/avatar_path")
            self.settings.sync()
        self._display_avatar_preview("")
        self.avatar_changed.emit("")

    def _commit_font_size(self, *_: object) -> None:
        value = self.font_size_combo.currentData()
        try:
            size = int(value)
        except (TypeError, ValueError):
            size = 10
        self.font_size_changed.emit(max(8, min(18, size)))

    def _emit_theme(self, *_: object) -> None:
        self.theme_changed.emit(str(self.theme_combo.currentData()))

    def _emit_background_highlight(self) -> None:
        self.background_highlight_changed.emit(str(self.background_highlight_combo.currentData() or "mint"))

    def _emit_font(self, *_: object) -> None:
        self.font_changed.emit(str(self.font_combo.currentData()))

    def _emit_numeric_font(self, *_: object) -> None:
        self.numeric_font_changed.emit(str(self.numeric_font_combo.currentData()))

    def _emit_ui_preferences(self, *_: object) -> None:
        self.ui_preferences_changed.emit(
            str(self.layout_direction_combo.currentData()),
            str(self.text_alignment_combo.currentData()),
            str(self.digits_combo.currentData()),
            str(self.table_alignment_combo.currentData()),
        )

    def _reset_ui_preferences(self) -> None:
        self.font_combo.setCurrentIndex(max(0, self.font_combo.findData("auto")))
        self.numeric_font_combo.setCurrentIndex(max(0, self.numeric_font_combo.findData("same")))
        self.font_size_combo.setCurrentIndex(max(0, self.font_size_combo.findData(10)))
        self.font_size_changed.emit(10)
        self.layout_direction_combo.setCurrentIndex(max(0, self.layout_direction_combo.findData("rtl")))
        self.text_alignment_combo.setCurrentIndex(max(0, self.text_alignment_combo.findData("right")))
        self.digits_combo.setCurrentIndex(max(0, self.digits_combo.findData("latin")))
        self.table_alignment_combo.setCurrentIndex(max(0, self.table_alignment_combo.findData("auto")))
        self._emit_ui_preferences()

