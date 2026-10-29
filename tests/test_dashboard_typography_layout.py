from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DashboardTypographyLayoutTests(unittest.TestCase):
    def setUp(self):
        self.pages = (ROOT / "nava_journal" / "pages.py").read_text(encoding="utf-8")
        self.theme = (ROOT / "nava_journal" / "theme.py").read_text(encoding="utf-8")
        self.components = (ROOT / "nava_journal" / "ui_components.py").read_text(encoding="utf-8")
        self.main_window = (ROOT / "nava_journal" / "main_window.py").read_text(encoding="utf-8")
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_global_font_size_is_in_a_dedicated_right_anchored_rtl_panel(self):
        self.assertIn("font_size_changed = Signal(int)", self.pages)
        self.assertIn('self.font_size_combo.setObjectName("globalFontSizeCombo")', self.pages)
        self.assertIn('font_size_panel.setObjectName("globalFontSizePanel")', self.pages)
        self.assertIn("font_size_panel.setLayoutDirection(Qt.LayoutDirection.LeftToRight)", self.pages)
        self.assertIn("font_size_row.setDirection(QBoxLayout.Direction.LeftToRight)", self.pages)
        self.assertLess(self.pages.index("font_size_row.addStretch(1)"), self.pages.index("font_size_row.addWidget(self.font_size_combo"))
        self.assertIn("font_size_title.setLayoutDirection(Qt.LayoutDirection.RightToLeft)", self.pages)
        self.assertIn("font_size_hint.setLayoutDirection(Qt.LayoutDirection.RightToLeft)", self.pages)
        self.assertIn("def enforce_font_size_layout(self)", self.pages)
        self.assertIn("QTimer.singleShot(0, self.enforce_font_size_layout)", self.pages)
        self.assertIn("self.settings_page.font_size_changed.connect(self.change_font_size)", self.main_window)
        self.assertIn('settings.value("appearance/font_size", 10, type=int)', self.main)
        self.assertIn("scale_local_stylesheets", self.theme)
        self.assertIn("self.settings_page.enforce_font_size_layout()", self.main_window)

    def test_welcome_title_subtitle_and_date_are_enforced_after_global_rtl(self):
        self.assertIn('greeting.addWidget(title_row_host)', self.pages)
        self.assertIn('greeting.addWidget(subtitle)', self.pages)
        self.assertIn('subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)', self.pages)
        self.assertIn("def enforce_local_layout(self)", self.pages)
        self.assertIn("def showEvent(self, event)", self.pages)
        self.assertIn("QTimer.singleShot(0, self.enforce_local_layout)", self.pages)
        self.assertIn("self.dashboard_page.enforce_local_layout()", self.main_window)
        self.assertIn('title_row.setDirection(QBoxLayout.Direction.LeftToRight)', self.pages)

    def test_dashboard_recent_header_is_enforced_after_refresh(self):
        self.assertIn('self._nava_recent_title_label = section_title', self.pages)
        self.assertIn('header_layout.setAlignment(self._nava_view_all_button, Qt.AlignmentFlag.AlignLeft', self.pages)
        self.assertIn('header_layout.setAlignment(heading_group, Qt.AlignmentFlag.AlignRight', self.pages)
        self.assertIn('self.recent_count_label.setText(f"{display_digits(len(entries))} مورد تازه")', self.pages)
        self.assertIn("self.enforce_local_layout()", self.pages)

    def test_recent_card_text_is_reanchored_right_after_global_preferences(self):
        block = self.pages[self.pages.index("class RecentEntryCard"):self.pages.index("class DashboardPage")]
        self.assertIn("def enforce_right_alignment(self)", block)
        self.assertIn("self._nava_details_layout = details", block)
        self.assertIn("widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)", block)
        self.assertIn('self.setProperty("navaPreserveLayoutDirection", True)', block)

    def test_combo_popup_uses_stable_standard_qt_view_without_custom_double_frame(self):
        self.assertIn("class NoWheelComboBox(QComboBox)", self.components)
        self.assertIn("if self.view().isVisible()", self.components)
        self.assertNotIn('popup.setObjectName("navaComboPopup")', self.components)
        self.assertNotIn("def showPopup(self)", self.components)
        self.assertNotIn("navaComboPopupContainer", self.theme)
        self.assertNotIn("QListView#navaComboPopup", self.theme)
        self.assertNotIn("min-height: 22px; border-radius: 9px; padding: 9px 11px", self.theme)
        self.assertIn("QComboBox QAbstractItemView, QComboBox QListView", self.theme)
        self.assertIn("QComboBox {{\n        background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']};\n        border-radius: 9px; padding: 9px 11px", self.theme)
        rtl = (ROOT / "nava_journal" / "rtl.py").read_text(encoding="utf-8")
        self.assertIn('if not widget.property("navaPreserveLayoutDirection"):', rtl)
        button_branch = rtl[rtl.index("elif isinstance(widget, QAbstractButton):"):rtl.index("if isinstance(widget, QTableWidget):")]
        self.assertIn('if not widget.property("navaPreserveLayoutDirection"):', button_branch)

    def test_metric_cards_keep_large_typography(self):
        self.assertIn('font-size: 20pt; font-weight: 850', self.theme)
        self.assertIn('font-size: 9.5pt; font-weight:750', self.theme)


if __name__ == "__main__":
    unittest.main()
