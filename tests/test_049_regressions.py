from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Release049RegressionTests(unittest.TestCase):
    def setUp(self):
        self.pages = (ROOT / "nava_journal" / "pages.py").read_text(encoding="utf-8")
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.main_window = (ROOT / "nava_journal" / "main_window.py").read_text(encoding="utf-8")
        self.theme = (ROOT / "nava_journal" / "theme.py").read_text(encoding="utf-8")
        self.ui = (ROOT / "nava_journal" / "ui_components.py").read_text(encoding="utf-8")

    def test_font_size_combo_is_persisted_and_global(self):
        self.assertIn("font_size_changed = Signal(int)", self.pages)
        self.assertIn("self.font_size_combo = NoWheelComboBox()", self.pages)
        self.assertIn('font_size_panel.setObjectName("globalFontSizePanel")', self.pages)
        self.assertIn("font_size_row.addWidget(self.font_size_combo", self.pages)
        self.assertIn("font_size_row.addStretch(1)", self.pages)
        self.assertIn("font_size_row.setDirection(QBoxLayout.Direction.LeftToRight)", self.pages)
        self.assertIn("def enforce_font_size_layout(self)", self.pages)
        self.assertIn('settings.value("appearance/font_size", 10, type=int)', self.main)
        self.assertIn("scale_local_stylesheets", self.theme)
        self.assertIn("self.settings_page.font_size_changed.connect(self.change_font_size)", self.main_window)
        self.assertIn("def change_font_size", self.main_window)

    def test_subtitle_is_in_expanding_greeting_column(self):
        block = self.pages[self.pages.index('greeting_host = QWidget()'):self.pages.index('local_badge = QFrame()', self.pages.index('greeting_host = QWidget()'))]
        self.assertIn("greeting = QVBoxLayout(greeting_host)", block)
        self.assertIn("greeting.addWidget(title_row_host)", block)
        self.assertIn("greeting.addWidget(subtitle)", block)
        self.assertIn("subtitle.setAlignment(Qt.AlignmentFlag.AlignRight", block)

    def test_all_recent_card_labels_are_right_aligned(self):
        block = self.pages[self.pages.index("class RecentEntryCard"):self.pages.index("class DashboardPage")]
        self.assertIn("widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)", block)
        self.assertIn("self._nava_details_layout = details", block)
        self.assertIn("widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)", block)
        self.assertIn('self.setProperty("navaPreserveLayoutDirection", True)', block)

    def test_popup_has_only_one_visible_rounded_frame(self):
        self.assertNotIn("def showPopup(self)", self.ui)
        self.assertNotIn("navaComboPopupContainer", self.ui)
        self.assertNotIn("QFrame#navaComboPopupContainer", self.theme)
        self.assertIn("QComboBox QAbstractItemView, QComboBox QListView", self.theme)


if __name__ == "__main__":
    unittest.main()
