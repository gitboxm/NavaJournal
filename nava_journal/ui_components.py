"""Reusable modern UI components for Nava Journal."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGraphicsOpacityEffect,
    QLayout, QLayoutItem, QSizePolicy, QTextEdit, QWidget,
)

from .theme import theme_colors
from .rtl import display_digits


class FlowLayout(QLayout):
    """A wrapping layout for tag chips; starts on the right for RTL interfaces."""

    def __init__(self, parent: QWidget | None = None, margin: int = 0, h_spacing: int = 8, v_spacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt API
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt API
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:  # noqa: N802 - Qt API
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt API
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt API
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _spacing(self, horizontal: bool) -> int:
        configured = self._h_spacing if horizontal else self._v_spacing
        if configured >= 0:
            return configured
        parent = self.parentWidget()
        if parent is None:
            return 8
        control = QSizePolicy.ControlType.PushButton
        orientation = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        return parent.style().layoutSpacing(control, control, orientation)

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        parent = self.parentWidget()
        rtl = parent is not None and parent.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = effective.right() + 1 if rtl else effective.x()
        y = effective.y()
        row_height = 0
        space_x = self._spacing(True)
        space_y = self._spacing(False)
        for item in self._items:
            hint = item.sizeHint()
            if rtl:
                next_x = x - hint.width() - space_x
                overflow = row_height > 0 and next_x < effective.x() - 1
                if overflow:
                    x = effective.right() + 1
                    y += row_height + space_y
                    next_x = x - hint.width() - space_x
                    row_height = 0
                if not test_only:
                    item.setGeometry(QRect(QPoint(x - hint.width() + 1, y), hint))
            else:
                next_x = x + hint.width() + space_x
                overflow = row_height > 0 and next_x - space_x > effective.right() + 1
                if overflow:
                    x = effective.x()
                    y += row_height + space_y
                    next_x = x + hint.width() + space_x
                    row_height = 0
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + bottom


class AutoGrowTextEdit(QTextEdit):
    """Multiline editor that grows with its content and has no inner scrollbars."""

    def __init__(self, parent: QWidget | None = None, min_height: int = 48):
        super().__init__(parent)
        self._min_height = min_height
        self.setMinimumHeight(min_height)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.document().documentLayout().documentSizeChanged.connect(self._sync_height)
        self._sync_height()

    def _sync_height(self, *_: object) -> None:
        try:
            doc_height = self.document().documentLayout().documentSize().height()
            target = max(self._min_height, int(doc_height + self.frameWidth() * 2 + 20))
            if self.height() != target:
                self.setFixedHeight(target)
        except RuntimeError:
            pass


class ProgressRing(QWidget):
    """Compact animated-dashboard ring, with colors adapted to the active theme."""

    def __init__(self, value: int = 100, parent: QWidget | None = None, diameter: int = 88):
        super().__init__(parent)
        self.value = max(0, min(100, int(value)))
        self.diameter = max(56, int(diameter))
        self.setObjectName("progressRing")
        self.setFixedSize(self.diameter, self.diameter)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_value(self, value: int) -> None:
        self.value = max(0, min(100, int(value)))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self.diameter, self.diameter)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        app = QApplication.instance()
        palette = theme_colors() if app is not None else theme_colors("dark")
        light = not bool(palette["is_dark"])
        track = palette["border_solid"]
        accent_start, accent_end = palette["accent"], palette["success"]
        scale = self.diameter / 88.0
        inset = max(4, round(7 * scale))
        pen_width = max(4, round(7 * scale))
        rect = self.rect().adjusted(inset, inset, -inset, -inset)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track_pen = QPen(QColor(track), pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 90 * 16, -360 * 16)
        gradient = QConicalGradient(QPointF(rect.center()), -90)
        gradient.setColorAt(0.0, QColor(accent_start))
        gradient.setColorAt(0.48, QColor(accent_end))
        gradient.setColorAt(1.0, QColor(accent_start))
        progress_pen = QPen(QBrush(gradient), pen_width)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(progress_pen)
        painter.drawArc(rect, 90 * 16, -int(360 * self.value / 100) * 16)
        painter.setPen(QColor(palette["text"]))
        font = painter.font()
        font.setPointSize(max(11, round(16 * scale)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, 0, 0, -2), Qt.AlignmentFlag.AlignCenter, display_digits(self.value))
        small = painter.font()
        small.setPointSize(max(6, round(8 * scale)))
        small.setBold(False)
        painter.setFont(small)
        painter.drawText(self.rect().adjusted(0, round(26 * scale), 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "%")
        painter.end()


def fit_combo_to_contents(combo: QComboBox, minimum_width: int = 0, maximum_width: int = 280) -> None:
    """Prefer the longest item width instead of stretching short option fields."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setMinimumWidth(max(0, int(minimum_width)))
    combo.setMaximumWidth(max(int(minimum_width), int(maximum_width)))
    combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    combo.adjustSize()


class NoWheelComboBox(QComboBox):
    """Use the standard Qt dropdown while preventing accidental wheel changes.

    This is the stable pre-custom-popup implementation: it does not replace the
    native QComboBox view, does not create an extra popup frame, and keeps the
    original theme stylesheet responsible for the dropdown appearance.
    """

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


def fade_in(widget: QWidget, duration_ms: int = 240, delay_ms: int = 0) -> QPropertyAnimation:
    """Play a lifecycle-safe fade-in for newly created cards.

    Older implementation removed QGraphicsOpacityEffect inside the animation's
    finished callback and scheduled animation.start with a global singleShot.
    Rapid page navigation could delete a card before its timer/animation ran. The
    timer and animation are now owned by the card; the effect is retained at 1.0,
    so deleting/rebuilding the card also cancels the whole animation tree safely.
    """
    previous = getattr(widget, "_nava_fade_animation", None)
    if previous is not None:
        try:
            previous.stop()
        except RuntimeError:
            pass
    effect = getattr(widget, "_nava_fade_effect", None)
    if effect is None:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        setattr(widget, "_nava_fade_effect", effect)
    effect.setOpacity(0.0)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(80, int(duration_ms)))
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    setattr(widget, "_nava_fade_animation", animation)
    timer = QTimer(widget)
    timer.setSingleShot(True)
    timer.timeout.connect(animation.start)
    setattr(widget, "_nava_fade_timer", timer)
    timer.start(max(0, int(delay_ms)))
    return animation
