"""Right-align only the first metadata row in latest-event cards."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QBoxLayout


def apply(card) -> None:
    row = getattr(card, "_nava_metadata_layout", None)
    if row is None:
        return
    row.setDirection(QBoxLayout.Direction.RightToLeft)
    # Align only labels attached directly to this metadata row. The title row,
    # dashboard, global RTL/LTR preference, and all other pages are untouched.
    for index in range(row.count()):
        item = row.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, QLabel):
            widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
