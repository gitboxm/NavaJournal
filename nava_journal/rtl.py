"""Global layout direction, text alignment and localized digit preferences."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QTableWidget, QTextEdit, QWidget,
)

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
CENTERED_ROLE = Qt.ItemDataRole.UserRole + 2


def _app_property(name: str, default: str) -> str:
    app = QApplication.instance()
    if app is None:
        return default
    value = app.property(name)
    return str(value) if value not in (None, "") else default


def layout_mode() -> str:
    return _app_property("nava_layout_direction", "rtl")


def text_alignment_mode() -> str:
    return _app_property("nava_text_alignment", "right")


def table_alignment_mode() -> str:
    return _app_property("nava_table_alignment", "auto")


def digit_mode() -> str:
    return _app_property("nava_digit_mode", "latin")


def display_digits(value: object, mode: str | None = None) -> str:
    """Render digits consistently from settings, without changing stored values."""
    text = str(value)
    selected = mode or digit_mode()
    return text.translate(_FA_DIGITS) if selected == "persian" else text.translate(_EN_DIGITS)


def _alignment(mode: str, direction: str | None = None) -> Qt.AlignmentFlag:
    layout_direction = direction or layout_mode()
    if mode == "left":
        horizontal = Qt.AlignmentFlag.AlignLeft
    elif mode == "center":
        horizontal = Qt.AlignmentFlag.AlignHCenter
    elif mode == "start":
        horizontal = Qt.AlignmentFlag.AlignRight if layout_direction == "rtl" else Qt.AlignmentFlag.AlignLeft
    else:
        horizontal = Qt.AlignmentFlag.AlignRight
    return horizontal | Qt.AlignmentFlag.AlignVCenter


def text_alignment_flags() -> Qt.AlignmentFlag:
    return _alignment(text_alignment_mode(), layout_mode())


def table_alignment_flags() -> Qt.AlignmentFlag:
    selected = table_alignment_mode()
    if selected == "auto":
        selected = text_alignment_mode()
    return _alignment(selected, layout_mode())




def _inside_forced_rtl(widget: QWidget) -> bool:
    """Return True for UI islands whose reading direction is always Persian RTL."""
    current: QWidget | None = widget
    while current is not None:
        if current.objectName() == "memoriesPage" or bool(current.property("navaForceRtl")):
            return True
        current = current.parentWidget()
    return False

def _inside_sidebar(widget: QWidget) -> bool:
    current: QWidget | None = widget
    while current is not None:
        if current.objectName() == "sidebar":
            return True
        current = current.parentWidget()
    return False


def apply_rtl(root: QWidget) -> None:
    """Apply saved alignment/direction preferences to existing and dynamic widgets."""
    mode = layout_mode()
    direction = Qt.LayoutDirection.RightToLeft if mode == "rtl" else Qt.LayoutDirection.LeftToRight
    chosen_align = text_alignment_flags()
    table_align = table_alignment_flags()
    root.setLayoutDirection(direction)
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        object_name = widget.objectName()
        forced_rtl = _inside_forced_rtl(widget)
        inside_sidebar = _inside_sidebar(widget)
        widget_direction = Qt.LayoutDirection.RightToLeft if (forced_rtl or inside_sidebar) else direction
        if widget.property("navaPreserveLayoutDirection") and not forced_rtl:
            # Some compound controls use a fixed physical order independent of the
            # app text direction (e.g. Jalali year-month-day picker).
            pass
        elif forced_rtl:
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        elif object_name in {"mainRoot", "mainBody"}:
            # Structural shell is LTR intentionally: main_window.py adds the page
            # first and the sidebar second, pinning the sidebar to the physical right.
            # Text-bearing page content below remains RTL.
            widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        elif object_name == "sidebar" or inside_sidebar:
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        else:
            widget.setLayoutDirection(direction)

        if isinstance(widget, QLabel):
            # Sidebar labels are Persian UI controls, not ordinary user-content text.
            # Their physical row is pinned independently from the app-wide direction.
            if widget.property("navaSidebarText") or (inside_sidebar and object_name == "sidebarNavLabel"):
                widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                continue
            if widget.property("navaPreserveCenter"):
                current = widget.alignment()
                vertical = current & (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignVCenter)
                widget.setAlignment(Qt.AlignmentFlag.AlignHCenter | (vertical or Qt.AlignmentFlag.AlignVCenter))
                continue
            if widget.property("navaPreserveAlignment") and not forced_rtl:
                continue
            current = widget.alignment()
            vertical = current & (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignVCenter)
            if forced_rtl:
                widget.setAlignment(Qt.AlignmentFlag.AlignRight | (vertical or Qt.AlignmentFlag.AlignVCenter))
            elif inside_sidebar:
                widget.setAlignment(Qt.AlignmentFlag.AlignRight | (vertical or Qt.AlignmentFlag.AlignVCenter))
            else:
                horizontal = chosen_align & (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignHCenter)
                widget.setAlignment(horizontal | (vertical or Qt.AlignmentFlag.AlignVCenter))

        elif isinstance(widget, QLineEdit):
            if widget.property("navaPreserveCenter"):
                widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            elif forced_rtl:
                widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif not widget.property("navaPreserveAlignment"):
                widget.setAlignment(chosen_align)

        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            if forced_rtl:
                widget.setAlignment(Qt.AlignmentFlag.AlignRight)
            elif not widget.property("navaPreserveAlignment"):
                widget.setAlignment(chosen_align & ~Qt.AlignmentFlag.AlignVCenter)

        elif isinstance(widget, QComboBox):
            if not widget.property("navaPreserveAlignment"):
                if widget.isEditable() and widget.lineEdit() is not None:
                    widget.lineEdit().setAlignment(chosen_align)
                model = widget.model()
                for index in range(widget.count()):
                    try:
                        model_item = model.item(index)
                        if model_item is not None:
                            model_item.setTextAlignment(chosen_align)
                    except AttributeError:
                        pass

        elif isinstance(widget, QCheckBox):
            widget.setLayoutDirection(widget_direction)

        elif isinstance(widget, QAbstractButton):
            # Respect the same explicit direction pin used by fixed-layout islands.
            # Previously this branch overrode it after the general QWidget pass,
            # which could mirror dashboard button content even when its row was pinned.
            if not widget.property("navaPreserveLayoutDirection"):
                widget.setLayoutDirection(widget_direction)
            if widget.property("nav"):
                # Sidebar navigation uses an explicit RTL row: label right, icon left.
                if widget.objectName() == "sidebarNavButton":
                    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                    widget.setProperty("navaPreserveLayoutDirection", True)
                else:
                    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                widget.setProperty("navaTextAlign", "right")
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()

        if isinstance(widget, QTableWidget):
            widget.setLayoutDirection(widget_direction)
            widget.horizontalHeader().setLayoutDirection(widget_direction)
            widget.horizontalHeader().setDefaultAlignment(table_align)
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    item = widget.item(row, column)
                    if item is None:
                        continue
                    # In Auto mode keep purpose-built centered columns (date, counts,
                    # timestamps and favorite symbols). Explicit Right/Left/Center
                    # choices override that default so the user can diagnose alignment.
                    if item.data(CENTERED_ROLE) and table_alignment_mode() == "auto":
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    else:
                        item.setTextAlignment(table_align)

        elif isinstance(widget, QHeaderView):
            widget.setLayoutDirection(widget_direction)
            widget.setDefaultAlignment(table_align)

        elif isinstance(widget, QListWidget):
            widget.setLayoutDirection(widget_direction)
            item_align = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if forced_rtl else chosen_align
            for index in range(widget.count()):
                item = widget.item(index)
                if item is not None:
                    item.setTextAlignment(item_align)

        elif isinstance(widget, QAbstractItemView):
            widget.setLayoutDirection(widget_direction)


def show_info(parent: QWidget | None, title: str, text: str) -> None:
    _show_message(parent, title, text, QMessageBox.Icon.Information)


def show_warning(parent: QWidget | None, title: str, text: str) -> None:
    _show_message(parent, title, text, QMessageBox.Icon.Warning)


def show_error(parent: QWidget | None, title: str, text: str) -> None:
    _show_message(parent, title, text, QMessageBox.Icon.Critical)


def confirm(parent: QWidget | None, title: str, text: str, default_yes: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Question)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.Yes if default_yes else QMessageBox.StandardButton.No)
    yes_button = box.button(QMessageBox.StandardButton.Yes)
    no_button = box.button(QMessageBox.StandardButton.No)
    if yes_button is not None:
        yes_button.setText("بله، ادامه بده")
    if no_button is not None:
        no_button.setText("خیر، انصراف")
    apply_rtl(box)
    return box.exec() == QMessageBox.StandardButton.Yes


def _show_message(parent: QWidget | None, title: str, text: str, icon: QMessageBox.Icon) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    ok_button = box.button(QMessageBox.StandardButton.Ok)
    if ok_button is not None:
        ok_button.setText("متوجه شدم")
    apply_rtl(box)
    box.exec()
