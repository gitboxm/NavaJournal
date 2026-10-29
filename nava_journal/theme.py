from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget


# Nava Journal theme system.
# Colors that need transparency use Qt's rgba(r, g, b, alpha) syntax; alpha is 0..255.
# Opaque window/popup tokens stay solid so transparent glass surfaces never make
# top-level dialogs, menus or combo popups unreadable.
THEME_PRESETS: dict[str, dict] = {
    "dark": {
        "name": "dark", "label": "تیرهٔ نئونی · Glass",
        "is_dark": True, "glass": True,
        "window": "#080D18", "sidebar": "rgba(11, 18, 34, 246)",
        "surface": "rgba(20, 29, 51, 224)", "surface2": "rgba(25, 38, 65, 215)",
        "surface3": "rgba(40, 53, 84, 236)", "border": "rgba(123, 146, 190, 105)",
        "border_solid": "#33415F", "border_soft": "rgba(123, 146, 190, 72)",
        "text": "#F3F7FF", "muted": "#A6B3CA",
        "accent": "#68F0D2", "accent_hover": "#8BFFE7", "accent_text": "#08231D",
        "success": "#5BE7BB", "warning": "#FFD166", "danger": "#FF6F91",
        "input": "rgba(10, 18, 34, 246)", "table_alt": "rgba(27, 39, 64, 220)",
        "selection": "rgba(104, 240, 210, 58)", "popup": "#121B2D",
        "semantic": {
            "normal": "#A6B3CA", "important": "#FFD166", "critical": "#FF7897",
            "followup_none": "#A6B3CA", "followup_pending": "#FFD166",
            "followup_in_progress": "#75CFFF", "followup_done": "#5BE7BB",
            "favorite": "#FFD166", "tag": "#68F0D2",
        },
    },
    "light": {
        "name": "light", "label": "روشن مینیمال · Minimal",
        "is_dark": False, "glass": False,
        "window": "#F5F7FB", "sidebar": "#FFFFFF",
        "surface": "#FFFFFF", "surface2": "#F8FAFE", "surface3": "#EDF1F8",
        "border": "#DCE3EF", "border_solid": "#DCE3EF", "border_soft": "#E7ECF4",
        "text": "#20283A", "muted": "#657187",
        "accent": "#6256D9", "accent_hover": "#5044C7", "accent_text": "#FFFFFF",
        "success": "#087F5B", "warning": "#9A6500", "danger": "#C93659",
        "input": "#FFFFFF", "table_alt": "#F8FAFE", "selection": "#E8E6FF",
        "popup": "#FFFFFF",
        "semantic": {
            "normal": "#66748B", "important": "#986100", "critical": "#C93659",
            "followup_none": "#66748B", "followup_pending": "#986100",
            "followup_in_progress": "#176BC0", "followup_done": "#087F5B",
            "favorite": "#986100", "tag": "#4C42C7",
        },
    },
    "linear": {
        "name": "linear", "label": "Modern Workspace · Linear",
        "is_dark": True, "glass": False,
        "window": "#101116", "sidebar": "#15161D",
        "surface": "#1A1B23", "surface2": "#20222B", "surface3": "#292C37",
        "border": "#343744", "border_solid": "#343744", "border_soft": "#2B2D37",
        "text": "#F2F3F8", "muted": "#969BAC",
        "accent": "#8C7BFF", "accent_hover": "#A195FF", "accent_text": "#171329",
        "success": "#4DD4A7", "warning": "#F2C46D", "danger": "#FC718A",
        "input": "#171922", "table_alt": "#1D1F28", "selection": "#302B4C",
        "popup": "#1B1D25",
        "semantic": {
            "normal": "#9DA4B5", "important": "#F2C46D", "critical": "#FC718A",
            "followup_none": "#9DA4B5", "followup_pending": "#F2C46D",
            "followup_in_progress": "#77B9FF", "followup_done": "#4DD4A7",
            "favorite": "#F2C46D", "tag": "#A195FF",
        },
    },
}

# Backward-compatible names for callers that used the original two-palette API.
DARK = THEME_PRESETS["dark"]
LIGHT = THEME_PRESETS["light"]
LINEAR = THEME_PRESETS["linear"]
THEME_NAMES = tuple(THEME_PRESETS)

# A separate, user-adjustable background glow. It changes only the workspace
# canvas, never the opacity of popups, dialogs, inputs or cards.
BACKGROUND_HIGHLIGHTS: dict[str, dict[str, str]] = {
    "none": {"label": "بدون هایلایت", "color": "#000000"},
    "mint": {"label": "نعنایی آرام", "color": "#47DCC0"},
    "blue": {"label": "آبی مه‌آلود", "color": "#5B9DFF"},
    "violet": {"label": "بنفش ملایم", "color": "#9B8AFB"},
    "amber": {"label": "کهربایی لطیف", "color": "#F3B95F"},
    "rose": {"label": "رز غبارآلود", "color": "#F078A8"},
    "ice": {"label": "یخی روشن", "color": "#78D8F2"},
}


def normalize_highlight(value: str | None) -> str:
    key = str(value or "mint").strip().casefold()
    aliases = {"off": "none", "green": "mint", "purple": "violet", "pink": "rose"}
    key = aliases.get(key, key)
    return key if key in BACKGROUND_HIGHLIGHTS else "mint"


def _content_background(mode: str, highlight: str) -> str:
    """Create a very soft radial workspace glow with an opaque final stop."""
    palette = theme_colors(mode)
    selected = normalize_highlight(highlight)
    if selected == "none":
        return palette["window"]
    color = QColor(BACKGROUND_HIGHLIGHTS[selected]["color"])
    alpha = 44 if palette["is_dark"] else 25
    # Less saturated light-mode glows keep the page clean and editorial.
    center = f"rgba({color.red()},{color.green()},{color.blue()},{alpha})"
    mid = f"rgba({color.red()},{color.green()},{color.blue()},{max(1, alpha // 3)})"
    return (
        "qradialgradient(cx:0.82, cy:0.06, radius:1.12, fx:0.82, fy:0.06, "
        f"stop:0 {center}, stop:0.48 {mid}, stop:1 {palette['window']})"
    )


def normalize_theme(mode: str | None) -> str:
    """Resolve historical settings values to a supported preset."""
    aliases = {"neon": "dark", "glass": "dark", "minimal": "light", "workspace": "linear"}
    selected = str(mode or "dark").strip().casefold()
    selected = aliases.get(selected, selected)
    return selected if selected in THEME_PRESETS else "dark"


def theme_colors(mode: str | None = None) -> dict:
    """Return the shared palette for a named preset or the currently active app theme."""
    if mode is None:
        app = QApplication.instance()
        mode = app.property("nava_theme_mode") if app is not None else "dark"
    return THEME_PRESETS[normalize_theme(str(mode))]


def semantic_color(name: str, mode: str | None = None) -> str:
    """Theme-aware colors for status chips, importance and follow-up markers."""
    palette = theme_colors(mode)
    return str(palette.get("semantic", {}).get(name, palette["accent"]))


def contrast_foreground(hex_color: str) -> str:
    """Choose black or white text by WCAG relative luminance for solid accent fills."""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return "#FFFFFF"
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    white_ratio = 1.05 / (luminance + 0.05)
    dark_ratio = (luminance + 0.05) / 0.05
    return "#FFFFFF" if white_ratio >= dark_ratio else "#10131B"


def _icon_uri(name: str) -> str:
    """Prefer crisp SVG icon assets, falling back to PNG if SVG is unavailable."""
    root = Path(__file__).resolve().parent / "assets" / "icons"
    for suffix in (".svg", ".png"):
        path = root / f"{name}{suffix}"
        if path.is_file():
            return path.as_posix()
    return ""


def _font_families() -> tuple[str, str]:
    """Choose installed fonts by role; do not bundle or assume a font is installed."""
    try:
        available = {name.casefold(): name for name in QFontDatabase().families()}
    except Exception:
        available = {}

    def pick(candidates: tuple[str, ...], fallback: str) -> str:
        for candidate in candidates:
            if candidate.casefold() in available:
                return available[candidate.casefold()]
        return fallback

    persian = pick(("Vazirmatn UI", "Vazirmatn", "IRANSansX", "IRANSans", "Shabnam", "Sahel", "Noto Sans Arabic", "Segoe UI", "Tahoma"), "Tahoma")
    numeric = pick(("Segoe UI Variable", "Segoe UI", "Inter", "Arial", "Tahoma"), "Tahoma")
    return persian, numeric


def stylesheet(
    mode: str = "dark",
    font_family: str | None = None,
    numeric_font_family: str | None = None,
    base_font_size: int = 10,
    background_highlight: str | None = None,
) -> str:
    mode = normalize_theme(mode)
    c = theme_colors(mode)
    is_dark = bool(c["is_dark"])
    app = QApplication.instance()
    is_rtl = app is None or str(app.property("nava_layout_direction") or "rtl") == "rtl"
    saved_highlight = (
        background_highlight if background_highlight is not None
        else (str(app.property("nava_background_highlight") or "mint") if app is not None else "mint")
    )
    highlight_mode = normalize_highlight(saved_highlight)
    content_background = _content_background(mode, highlight_mode)
    default_persian, default_numeric = _font_families()
    # Shared design tokens: all new widgets use the same spacing/radius scale.
    spacing = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 22, "2xl": 28}
    radius = {"sm": 8, "md": 12, "lg": 16, "xl": 22, "2xl": 28}
    # Persistent outlines provide clear separation even when the pointer is elsewhere.
    recent_border = c["border_soft"]
    combo_arrow = _icon_uri("chevron-down-dark" if is_dark else "chevron-down-light")
    checkbox_check = _icon_uri("check-dark" if c["accent_text"] != "#FFFFFF" else "check-light")
    combo_side = "left" if is_rtl else "right"
    combo_other_side = "right" if is_rtl else "left"
    persian_font = font_family if font_family and font_family != "auto" else default_persian
    numeric_font = numeric_font_family if numeric_font_family and numeric_font_family != "same" else persian_font
    if not numeric_font or numeric_font == "auto":
        numeric_font = default_numeric
    css = f"""
    * {{ font-family: "{persian_font}"; font-size: 10pt; }}
    QWidget {{ color: {c['text']}; background: transparent; }}
    QMainWindow, QDialog, QMessageBox, QFileDialog, QColorDialog {{ background: {c['window']}; color: {c['text']}; }}
    QMainWindow#mainWindow, QWidget#mainRoot, QWidget#mainBody, QFrame#contentPanel {{ background: {c['window']}; }}
    QDialog, QMessageBox, QFileDialog, QColorDialog {{ background: {c['window']}; }}
    QWidget#mainRoot {{ background: {c['window']}; border: 1px solid {c['border']}; border-radius: 17px; }}
    QWidget#mainBody {{ background: {c['window']}; border: none; }}
    QWidget#globalFontSizePanel, QWidget#globalFontSizeRowHost,
    QWidget#globalFontSizeTitleRowHost, QWidget#globalFontSizeHintRowHost {{
        background: transparent; border: none;
    }}
    QFrame#appTitleBar {{
        background: {c['surface']}; border: none; border-bottom: 1px solid {c['border']}; border-top-left-radius: 16px; border-top-right-radius: 16px;
    }}
    QLabel#appTitleText {{ color: {c['text']}; font-size: 10pt; font-weight: 750; padding: 0 8px; }}
    QPushButton#windowControlButton, QPushButton#windowCloseButton {{
        background: transparent; border: 1px solid transparent; border-radius: 8px;
        padding: 0; min-height: 0; font-family: "Segoe UI Symbol"; font-size: 15pt;
    }}
    QPushButton#windowControlButton:hover {{ background: {c['surface3']}; border-color: {c['border']}; }}
    QPushButton#windowCloseButton:hover {{ background: #E04F65; color: #FFFFFF; border-color: #E04F65; }}
    QPushButton#toolbarSidebarToggle {{
        background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 10px; min-height: 0; padding: 0; font-size: 14pt; font-weight: 800;
    }}
    QPushButton#toolbarSidebarToggle:hover {{ background: {c['surface3']}; border-color: {c['accent']}; }}
    QLabel#databasePathValue {{
        font-family: "Consolas"; font-size: 9pt; color: {c['text']};
        background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 9px;
        padding: 8px 10px;
    }}
    QFrame#sidebar {{ background: {c['sidebar']}; border: none; border-left: 1px solid {c['border']}; }}
    QFrame#contentPanel {{ background: {content_background}; border: none; }}
    QFrame#dashboardTopRow {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['surface2']},stop:0.58 {c['surface']},stop:1 {c['surface3']});
        border: 1px solid {c['border']}; border-radius: 24px;
    }}
    QFrame#surfaceCard, QFrame#metricCard, QFrame#settingsCard {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 18px;
    }}
    QFrame#metricCard {{ padding: 2px; }}
    QLabel#sidebarNoteTitle {{ color: {c['text']}; font-weight: 750; font-size: 9.5pt; }}
    QFrame#heroCard {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['surface2']}, stop:1 {c['surface3']});
        border: 1px solid {c['border']}; border-radius: 24px;
    }}
    QFrame#dateCard {{
        background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 14px;
    }}
    QFrame#quoteCard {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 20px;
    }}
    QFrame#memoryHero {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['surface3']},stop:0.50 {c['surface']},stop:1 {c['surface2']});
        border: 1px solid {c['border']}; border-radius: 26px;
    }}
    QFrame#memoryHeroMark {{ background: {c['selection']}; border: 1px solid {c['accent']}; border-radius: 20px; }}
    QLabel#memoryHeroGlyph {{ color: {c['accent']}; font-size: 24pt; font-weight: 800; }}
    QFrame#memoryHeroDateWrap {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 18px; }}
    QFrame#memoryStatCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 17px; }}
    QFrame#memoryStatCard:hover {{ border-color: {c['accent']}; background: {c['surface2']}; }}
    QFrame#memoryEntryCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 20px; }}
    QFrame#memoryEntryCard[expanded="true"] {{ border-color: {c['accent']}; }}
    QFrame#memoryEntryCard:hover {{ border-color: {c['accent']}; }}
    QPushButton#memoryAccordionToggle {{
        background: transparent; color: {c['text']}; border: none; border-radius: 14px;
        padding: 8px 10px; text-align: right; min-height: 0; font-weight: 600;
    }}
    QPushButton#memoryAccordionToggle:hover {{ background: {c['surface2']}; }}
    QLabel#memoryAccordionArrow {{ color: {c['accent']}; background: {c['selection']}; border: 1px solid {c['border']}; border-radius: 10px; font-size: 15pt; font-weight: 800; min-width: 30px; min-height: 30px; }}
    QFrame#memoryAccordionDetails {{ background: {c['surface2']}; border: 1px solid {c['border_soft']}; border-radius: 14px; }}
    QLabel#memoryAccordionMeta {{ color: {c['muted']}; font-size: 8.5pt; }}
    QLabel#memoryAccordionBody {{ color: {c['text']}; font-size: 10pt; line-height: 1.6; }}
    QLabel#memoryAccordionTags {{ color: {c['accent']}; font-size: 9pt; }}
    QFrame#memoryYearColumn {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 17px; }}
    QFrame#memoryTimelineRail {{ background: {c['accent']}; border: none; border-radius: 2px; }}
    QFrame#memoryEmptyState {{ background: {c['surface']}; border: 1px dashed {c['border']}; border-radius: 24px; }}
    QFrame#memoryTodayChip {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 14px; }}
    QFrame#recentEntryCard {{
        background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['surface']},stop:1 {c['surface2']});
        border:1px solid {recent_border}; border-radius:16px;
    }}
    QFrame#recentEntryCard:hover {{ border:1px solid {c['accent']}; background:{c['surface2']}; }}
    QFrame#localDataCard {{
        background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['surface2']},stop:1 {c['surface']});
        border:1px solid {c['border']}; border-radius:17px;
    }}
    QFrame#localDataCard:hover {{ border-color:{c['accent']}; }}
    QFrame#attachmentItem {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {c['surface']},stop:1 {c['surface2']}); border:1px solid {c['border']}; border-radius:14px; }}
    QFrame#attachmentItem:hover {{ border-color:{c['accent']}; }}
    QFrame#tagChipPanel {{ background: transparent; border: none; }}
    QFrame#advancedSearchCard {{
        background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 16px;
    }}
    QFrame#advancedSearchCard QLabel#fieldLabel {{
        padding-top: 1px; padding-bottom: 3px; min-height: 22px; margin-bottom: 2px;
    }}
    QFrame#advancedSearchCard QLineEdit, QFrame#advancedSearchCard QComboBox {{
        min-height: 44px; padding: 6px 13px; border-radius: 10px;
    }}
    QFrame#advancedSearchCard QComboBox::drop-down {{ min-height: 42px; width: 34px; }}
    QFrame#advancedSearchCard QListWidget#filterTagList {{ min-height: 100px; max-height: 126px; }}
    QFrame#updateCard {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['surface']},stop:1 {c['surface2']});
        border: 1px solid {c['border']}; border-radius: 18px;
    }}
    QLabel {{ background: transparent; border: none; }}
    QLabel#pageTitle {{ font-size: 24pt; font-weight: 850; color: {c['text']}; padding-bottom: 2px; }}
    QLabel#heroTitle {{ font-size: 25pt; font-weight: 850; color: {c['text']}; padding-bottom: 2px; }}
    QLabel#memoryHeroTitle {{ font-size: 22pt; font-weight: 850; color: {c['text']}; }}
    QLabel#memoryHeroKicker {{ color: {c['accent']}; font-size: 9pt; font-weight: 850; }}
    QLabel#memoryHeroSubtitle {{ color: {c['muted']}; font-size: 10pt; }}
    QLabel#memoryHeroDate {{ color: {c['text']}; background: transparent; border: none; padding: 0; font-size: 12pt; font-weight: 850; }}
    QLabel#memoryYear {{ color: {c['accent']}; font-size: 16pt; font-weight: 900; }}
    QLabel#memoryYearCaption {{ color: {c['muted']}; font-size: 8pt; }}
    QLabel#memoryEntryTitle {{ color: {c['text']}; font-size: 13.5pt; font-weight: 850; }}
    QLabel#memoryExcerpt {{ color: {c['muted']}; font-size: 9.5pt; line-height: 1.55; }}
    QLabel#memoryFullDate {{ color: {c['muted']}; font-size: 8.5pt; font-weight: 700; }}
    QLabel#memoryMeta {{ color: {c['muted']}; font-size: 8.5pt; }}
    QLabel#memoryStatValue {{ color: {c['text']}; font-size: 17pt; font-weight: 850; }}
    QLabel#memoryStatLabel {{ color: {c['muted']}; font-size: 8.5pt; font-weight: 700; }}
    QLabel#memoryTodayLabel {{ color: {c['muted']}; font-size: 8pt; font-weight: 700; }}
    QLabel#memoryCategory {{ color: {c['accent']}; background: {c['selection']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 3px 8px; font-size: 8.5pt; font-weight: 700; }}
    QLabel#memoryArchived {{ color: {c['warning']}; background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 3px 8px; font-size: 8pt; }}
    QLabel#memoryEmptyMark {{ color: {c['accent']}; font-size: 28pt; }}
    QLabel#sectionTitle {{ font-size: 13pt; font-weight: 750; color: {c['text']}; }}
    QLabel#recentTitle {{ font-size: 10.5pt; font-weight: 750; color: {c['text']}; }}
    QLabel#recentPerson {{ color:{c['text']}; font-size:9pt; font-weight:700; }}
    QLabel#recentTags {{ color:{c['accent']}; font-size:8pt; font-weight:600; }}
    QLabel#recentAttachmentCount {{ color:{c['muted']}; font-size:8pt; padding:2px 5px; }}
    QLabel#recentMetaChip {{ font-size:8pt; font-weight:650; }}
    QLabel#recentFavorite {{ color:{c['warning']}; font-size:12pt; font-weight:800; }}
    QLabel#recentTagCount {{ color:{c['accent']}; background:{c['surface2']}; border:1px solid {c['border']}; border-radius:8px; padding:3px 7px; font-size:8.5pt; }}
    QLabel#recentCountBadge, QLabel#journalCountBadge {{ color:{c['accent']}; background:{c['selection']}; border:1px solid {c['accent']}; border-radius:10px; padding:5px 10px; font-weight:800; }}
    QLabel#localDataTitle {{ color:{c['muted']}; font-size:9pt; font-weight:700; }}
    QLabel#localDataSize {{ color:{c['text']}; font-size:15pt; font-weight:850; }}
    QLabel#attachmentNote {{ color:{c['accent']}; background:{c['surface2']}; border:1px dashed {c['border']}; border-radius:8px; padding:6px 9px; }}
    QLabel#dateFieldLabel {{ color:{c['muted']}; font-size:9pt; font-weight:700; }}
    QLabel#quoteText {{ font-size: 12pt; font-weight: 700; color: {c['text']}; line-height: 1.4; }}
    QLabel#dateBadge {{ color: {c['accent']}; background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px 10px; font-weight: 700; }}
    QLabel#recentDateChip {{ font-family: "{numeric_font}"; font-size: 9pt; font-weight: 750; }}
    QLabel#pillLabel {{ background: {c['surface2']}; color: {c['muted']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 4px 8px; font-size: 8.5pt; }}
    QWidget#progressRing {{ background: transparent; }}
    QLabel#fieldLabel {{ font-size: 10pt; font-weight: 700; color: {c['text']}; }}
    QLabel#datePreview {{ color: {c['accent']}; font-family: "{numeric_font}"; font-size: 10pt; font-weight: 700; padding-top: 4px; }}
    QLabel#muted {{ color: {c['muted']}; }}
    QLabel#eyebrow {{ color: {c['accent']}; font-family: "{numeric_font}"; font-size: 8pt; font-weight: 750; letter-spacing: 1.4px; }}
    QLabel#metricValue {{ font-family: "{numeric_font}"; font-size: 20pt; font-weight: 850; color: {c['text']}; }}
    QLabel#metricLabel {{ color: {c['text']}; font-size: 9.5pt; font-weight:750; }}
    QLabel#metricDetail {{ color: {c['muted']}; font-size: 8pt; }}
    QLabel#quoteSource {{ color: {c['muted']}; font-size: 8pt; }}
    QLabel#settingsAvatarPreview {{ font-size: 21pt; font-weight:800; }}
    QLabel#updateVersion {{ color: {c['accent']}; font-size: 11pt; font-weight: 800; padding: 4px 0; }}
    QLabel#updateStatus {{ color: {c['success']}; line-height: 1.55; }}
    QLabel#warningText {{ color: {c['danger']}; line-height: 1.55; }}
    QPushButton {{
        background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 12px; padding: 10px 16px; min-height: 22px; font-weight: 650;
    }}
    QPushButton:hover {{ background: {c['surface3']}; border-color: {c['accent']}; }}
    QPushButton:pressed {{ padding-top: 10px; padding-bottom: 8px; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
    QPushButton[primary="true"] {{
        background: {c['accent']}; color:{c['accent_text']}; border:1px solid {c['accent']};
        font-weight:800; padding:10px 17px; border-radius:12px;
    }}
    QPushButton[secondary="true"] {{
        background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']};
        font-weight: 700; padding: 9px 14px; border-radius: 12px;
    }}
    QPushButton[secondary="true"]:hover {{ background: {c['surface3']}; border-color: {c['accent']}; }}
    QPushButton[primary="true"]:hover {{ background:{c['accent_hover']}; border-color:{c['accent_hover']}; }}
    QPushButton[danger="true"] {{ color: {c['danger']}; }}
    QPushButton[chip="true"] {{ border-radius: 15px; padding: 7px 12px; min-height: 0; background: {c['surface2']}; }}
    QPushButton[chip="true"]:checked {{ background: {c['accent']}; color: {c['accent_text']}; border-color: {c['accent']}; font-weight: 700; }}
    QPushButton[compact="true"] {{ padding: 5px 9px; min-height: 0; border-radius: 8px; }}
    QPushButton#dashboardNewEntry {{ padding:11px 20px; border-radius:13px; min-width:190px; }}
    QPushButton[nav="true"], QPushButton#sidebarNavButton {{
        text-align: right; padding: 0; border-radius: {radius['lg']}px; border: 1px solid transparent;
        background: transparent; color: {c['muted']}; font-weight: 700;
    }}
    QPushButton#sidebarNavButton {{ padding: 0; }}
    QLabel#sidebarNavLabel {{ color: {c['muted']}; background: transparent; border: none; font-weight: 700; padding: 0 2px; }}
    QPushButton#sidebarNavButton[active="true"] QLabel#sidebarNavLabel {{ color: {c['text']}; font-weight: 800; }}
    QPushButton[nav="true"]:hover {{ background: {c['surface2']}; color: {c['text']}; }}
    QPushButton[nav="true"][active="true"] {{ background: {c['surface3']}; color: {c['text']}; border-color: {c['border']}; border-right: 3px solid {c['accent']}; }}
    QPushButton[nav="true"][navaTextAlign="left"] {{ text-align: left; }}
    QPushButton[nav="true"][navaTextAlign="right"] {{ text-align: right; }}
    QPushButton[nav="true"][navaTextAlign="center"] {{ text-align: center; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDateEdit {{
        background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 13px; padding: 11px 14px; selection-background-color: {c['selection']};
    }}
    QComboBox {{
        background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: {radius['md']}px; padding: 11px {spacing['md']}px; padding-{combo_side}: {spacing['md'] + 22}px;
        padding-{combo_other_side}: {spacing['md']}px; selection-background-color: {c['selection']}; min-height: 20px;
    }}
    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{
        border-color: {c['accent']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDateEdit:focus {{
        border: 1px solid {c['accent']}; background: {c['surface']};
    }}
    QComboBox:focus {{ border: 1px solid {c['accent']}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top {combo_side}; width: 34px;
        border: none; border-{combo_side}: 1px solid {c['border_soft']};
        border-top-{combo_side}-radius: {radius['md']}px; background: transparent;
    }}
    QComboBox::down-arrow {{ image: url("{combo_arrow}"); width: 12px; height: 12px; }}
    QComboBox::down-arrow:on {{ top: 1px; }}
    QComboBox:disabled::down-arrow {{ image: url("{combo_arrow}"); }}
    QComboBox QAbstractItemView, QCompleter QAbstractItemView {{
        background: {c['popup']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: {radius['md']}px; padding: 5px; outline: 0;
        selection-background-color: {c['selection']}; selection-color: {c['text']};
    }}
    QComboBox QAbstractItemView::item, QCompleter QAbstractItemView::item {{ padding: 8px 10px; min-height: 26px; border-radius: 7px; }}
    QComboBox QAbstractItemView::item:selected, QCompleter QAbstractItemView::item:selected {{ background: {c['selection']}; }}
    QMenu {{ background: {c['popup']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: {radius['lg']}px; padding: 7px; }}
    QMenu::item {{ padding: 9px 28px 9px 14px; border-radius: 9px; margin: 2px 3px; background: transparent; min-height: 24px; }}
    QMenu::item:selected {{ background: {c['selection']}; color: {c['text']}; border: 1px solid {c['accent']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 10px; }}
    QCheckBox {{ spacing: 9px; color: {c['text']}; background: transparent; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 5px; border: 1px solid {c['border']}; background: {c['input']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{checkbox_check}"); }}
    QTableWidget, QTableView {{ background: {c['surface']}; alternate-background-color: {c['table_alt']}; gridline-color: {c['border']}; border: 1px solid {c['border']}; border-radius: 12px; selection-background-color: {c['selection']}; selection-color: {c['text']}; outline: 0; font-family: "{numeric_font}"; }}
    QTableWidget::item {{ font-family: "{numeric_font}"; }}
    QHeaderView::section {{ background: {c['surface2']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']}; padding: 12px 8px; font-weight: 700; }}
    QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {c['border']}; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 12px; top: -1px; background: {c['surface']}; }}
    QTabBar::tab {{ background: {c['surface2']}; color: {c['muted']}; border: 1px solid {c['border']}; border-bottom: none; padding: 11px 22px; margin-left: 5px; border-top-left-radius: 9px; border-top-right-radius: 9px; }}
    QTabBar::tab:selected {{ background: {c['surface']}; color: {c['text']}; border-color: {c['accent']}; font-weight: 700; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 12px; margin: 3px 0; }}
    QListWidget::item:hover {{ background: {c['surface2']}; border-color: {c['accent']}; }}
    QListWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
    QListWidget#entryTagList, QListWidget#filterTagList, QListWidget#updateTimeline {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 4px;
    }}
    QListWidget#entryTagList::item, QListWidget#filterTagList::item, QListWidget#updateTimeline::item {{
        background: transparent; border: none; border-radius: 7px; padding: 5px 8px; margin: 1px 0;
    }}
    QListWidget#entryTagList::item:hover, QListWidget#filterTagList::item:hover {{ background: {c['surface2']}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 34px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QProgressBar {{ border: 1px solid {c['border']}; border-radius: 5px; background: {c['surface2']}; text-align: center; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
    QGroupBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {radius['lg']}px; margin-top: 14px; padding: 15px 12px 10px; font-weight: 700; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: {c['muted']}; }}
    QRadioButton {{ color: {c['text']}; background: transparent; spacing: 8px; }}
    QRadioButton::indicator {{ width: 17px; height: 17px; border-radius: 9px; border: 1px solid {c['border']}; background: {c['input']}; }}
    QRadioButton::indicator:checked {{ background: {c['accent']}; border: 4px solid {c['surface']}; outline: 1px solid {c['accent']}; }}
    QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {{ min-height: 20px; padding: 8px 11px; border-radius: {radius['md']}px; background: {c['input']}; border: 1px solid {c['border']}; selection-background-color: {c['selection']}; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QDateEdit::up-button, QDateEdit::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{ width: 20px; border: none; background: transparent; }}
    QDateTimeEdit QCalendarWidget QWidget {{ background: {c['popup']}; color: {c['text']}; }}
    QCalendarWidget QToolButton {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px; }}
    QCalendarWidget QAbstractItemView {{ background: {c['popup']}; color: {c['text']}; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; alternate-background-color: {c['surface2']}; }}
    QSlider::groove:horizontal {{ height: 5px; border-radius: 3px; background: {c['surface3']}; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {c['surface']}; border: 2px solid {c['accent']}; width: 15px; margin: -6px 0; border-radius: 8px; }}
    QToolButton {{ color: {c['text']}; background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: {radius['sm']}px; padding: 5px; }}
    QToolButton:hover {{ background: {c['surface3']}; border-color: {c['accent']}; }}
    QTreeWidget, QTreeView, QListView {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: {radius['md']}px; alternate-background-color: {c['table_alt']}; selection-background-color: {c['selection']}; selection-color: {c['text']}; outline: 0; }}
    QTreeWidget::item, QTreeView::item, QListView::item {{ padding: 7px; border-radius: 6px; }}
    QTreeWidget::item:hover, QTreeView::item:hover, QListView::item:hover {{ background: {c['surface2']}; }}
    QTreeWidget::item:selected, QTreeView::item:selected, QListView::item:selected {{ background: {c['selection']}; }}
    QHeaderView::section:horizontal {{ border-right: 1px solid {c['border_soft']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 3px; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 34px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QProgressBar {{ border: 1px solid {c['border']}; border-radius: {radius['sm']}px; background: {c['surface2']}; text-align: center; color: {c['text']}; min-height: 12px; padding: 1px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
    QFrame#toastCard, QFrame#notificationCard {{ background: {c['popup']}; color: {c['text']}; border: 1px solid {c['border']}; border-left: 3px solid {c['accent']}; border-radius: {radius['lg']}px; }}
    QStatusBar {{ background: {c['sidebar']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
    QToolTip {{ color: {c['text']}; background: {c['popup']}; border: 1px solid {c['border']}; border-radius: {radius['sm']}px; padding: 7px 9px; }}
    QMenu, QCompleter QAbstractItemView, QComboBox QAbstractItemView {{ background-color: {c['popup']}; }}
    """
    size = max(8, min(18, int(base_font_size)))
    factor = size / 10.0
    css = re.sub(
        r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)pt",
        lambda match: f"font-size: {float(match.group(1)) * factor:.2f}pt",
        css,
        flags=re.IGNORECASE,
    )
    return css


def scale_local_stylesheets(app: QApplication, base_font_size: int) -> None:
    """Scale point-size fonts in widget-local stylesheets without compounding."""
    size = max(8, min(18, int(base_font_size)))
    factor = size / 10.0
    for widget in QApplication.allWidgets():
        current = widget.styleSheet()
        if not current:
            continue
        previous_applied = widget.property("navaScaledLocalStylesheet")
        original = widget.property("navaOriginalLocalStylesheet")
        if previous_applied and current == previous_applied and original is not None:
            base_css = str(original)
        else:
            base_css = current
            widget.setProperty("navaOriginalLocalStylesheet", base_css)
        scaled_css = re.sub(
            r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)pt",
            lambda match: f"font-size: {float(match.group(1)) * factor:.2f}pt",
            base_css,
            flags=re.IGNORECASE,
        )
        if scaled_css != current:
            widget.setStyleSheet(scaled_css)
        widget.setProperty("navaScaledLocalStylesheet", scaled_css)


def apply_theme(
    app: QApplication,
    mode: str,
    font_family: str | None = None,
    numeric_font_family: str | None = None,
    base_font_size: int = 10,
    background_highlight: str | None = None,
) -> None:
    default_persian, default_numeric = _font_families()
    selected = font_family if font_family and font_family != "auto" else default_persian
    selected_numeric = (
        selected if numeric_font_family in (None, "", "same")
        else (default_numeric if numeric_font_family == "auto" else numeric_font_family)
    )
    base_size = max(8, min(18, int(base_font_size)))
    app.setFont(QFont(selected, base_size))
    app.setProperty("nava_base_font_size", base_size)
    mode = normalize_theme(mode)
    palette = theme_colors(mode)
    # Keep labels accessible on every accent surface: compute contrast for solid primary fills.
    palette["accent_text"] = contrast_foreground(palette["accent"])
    if background_highlight is None:
        background_highlight = str(app.property("nava_background_highlight") or "mint")
    background_highlight = normalize_highlight(background_highlight)
    app.setProperty("nava_theme_mode", mode)
    app.setProperty("nava_theme_is_dark", bool(palette["is_dark"]))
    app.setProperty("nava_background_highlight", background_highlight)
    app.setProperty("nava_ui_font_family", selected)
    app.setProperty("nava_numeric_font_family", selected_numeric)
    app.setStyleSheet(stylesheet(mode, selected, selected_numeric, base_size, background_highlight))
    scale_local_stylesheets(app, base_size)
