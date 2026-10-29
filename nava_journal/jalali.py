from __future__ import annotations

from datetime import date, datetime
from persiantools.jdatetime import JalaliDate

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]


def to_fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def to_en_digits(value: object) -> str:
    return str(value).translate(_EN_DIGITS)


def current_jalali() -> JalaliDate:
    return JalaliDate.today()


def jalali_parts_from_iso(iso_date: str) -> tuple[int, int, int]:
    gregorian = date.fromisoformat(iso_date[:10])
    jalali = JalaliDate(gregorian)
    return jalali.year, jalali.month, jalali.day


def iso_from_jalali(year: int, month: int, day: int) -> str:
    return JalaliDate(int(year), int(month), int(day)).to_gregorian().isoformat()


def jalali_iso_today() -> str:
    return current_jalali().to_gregorian().isoformat()


def format_jalali(
    iso_date: str,
    persian_digits: bool = False,
    separator: str = ".",
    short_year: bool = True,
) -> str:
    """Format a stored ISO date as Jalali.

    UI default is compact YY.MM.DD (for example 05.08.07). The database stores the full Gregorian ISO date and a full Jalali date in a
    separate column. Pass short_year=False only for diagnostics that need YYYY.MM.DD.
    """
    y, m, d = jalali_parts_from_iso(iso_date)
    shown_year = y % 100 if short_year else y
    year_width = 2 if short_year else 4
    result = f"{shown_year:0{year_width}d}{separator}{m:02d}{separator}{d:02d}"
    return to_fa_digits(result) if persian_digits else result


def format_jalali_full(iso_date: str, persian_digits: bool = False, separator: str = ".") -> str:
    """Format an ISO date with the four-digit Jalali year."""
    return format_jalali(iso_date, persian_digits=persian_digits, separator=separator, short_year=False)


def jalali_sort_key(iso_date: str) -> int:
    """A century-aware key, so compact date labels can still sort correctly."""
    year, month, day = jalali_parts_from_iso(iso_date)
    return year * 10000 + month * 100 + day


def format_timestamp(timestamp: str, persian_digits: bool = False) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
        date_part = format_jalali(dt.date().isoformat(), persian_digits=False, separator=".")
        result = f"{date_part}  {dt:%H:%M}"
        return to_fa_digits(result) if persian_digits else result
    except (ValueError, TypeError):
        return timestamp or "—"


def month_day_count(year: int, month: int) -> int:
    # JalaliDate validates leap years and month lengths rather than duplicating calendar math.
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    try:
        JalaliDate(year, 12, 30)
        return 30
    except ValueError:
        return 29


def year_month_label(year: int, month: int) -> str:
    return f"{to_fa_digits(year)} {MONTHS[month - 1]}"
