"""Dashboard-only alignment refinements, installed as a selectable update group."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout


def apply(page) -> None:
    section = getattr(page, "_nava_recent_section_layout", None)
    heading = getattr(page, "_nava_recent_heading_group", None)
    view_all = getattr(page, "_nava_view_all_button", None)
    quick_actions = getattr(page, "_nava_quick_action_layout", None)
    new_button = getattr(page, "new_button", None)

    # Preserve the overall dashboard layout; only pin the requested elements.
    if section is not None:
        section.setDirection(QBoxLayout.Direction.LeftToRight)
        if view_all is not None:
            section.setAlignment(view_all, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if heading is not None:
            heading.setDirection(QBoxLayout.Direction.RightToLeft)
            section.setAlignment(heading, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if quick_actions is not None:
        quick_actions.setDirection(QBoxLayout.Direction.RightToLeft)
        if new_button is not None:
            quick_actions.setAlignment(new_button, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
