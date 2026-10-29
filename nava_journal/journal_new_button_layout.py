"""Anchor the journal's new-event button on the right without changing page flow."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout


def apply(page) -> None:
    header = getattr(page, "_nava_header_layout", None)
    button = getattr(page, "new_button", None)
    title_column = getattr(page, "_nava_title_column", None)
    if header is None:
        return
    header.setDirection(QBoxLayout.Direction.LeftToRight)
    if title_column is not None:
        header.setAlignment(title_column, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    if button is not None:
        header.setAlignment(button, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
