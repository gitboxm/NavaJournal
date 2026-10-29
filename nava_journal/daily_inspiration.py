"""Daily inspiration backed by the Persian Wikiquote community collection.

The online source is the Persian Wikiquote page ``گفتاورد``. Because the page is a
community-maintained quotation collection rather than a guaranteed daily-feed API,
we select one source quotation per local calendar day. The selected text and source
metadata are cached by the UI; an original offline message is used if the source is
unavailable. No quotation attribution is invented for the offline messages.
"""
from __future__ import annotations

from datetime import date
import hashlib
import html
import json
import re
from typing import Any

SOURCE_URL = "https://fa.wikiquote.org/wiki/%DA%AF%D9%81%D8%AA%D8%A7%D9%88%D8%B1%D8%AF"
SOURCE_LABEL = "ویکی‌گفتاورد فارسی"
SOURCE_API_URL = "https://fa.wikiquote.org/w/api.php"

# Original reminders written for Nava Journal, not presented as quotations from a
# historical author. Date-based selection makes the offline mode change each day.
OFFLINE_MESSAGES: tuple[str, ...] = (
    "برای بهترشدن لازم نیست همه‌چیز را امروز حل کنی؛ یک قدم روشن کافی است.",
    "پیشرفت آرامی که ادامه پیدا کند، از جهش کوتاهی که رها شود ماندگارتر است.",
    "ثبت‌کردن یک فکر خوب، راه بازگشت به آن را در روزهای شلوغ باز می‌گذارد.",
    "به‌جای کامل‌بودن، روی انجام‌دادن قدم بعدی تمرکز کن.",
    "گاهی بهترین تصمیم این است که مسئله را روشن‌تر بنویسی و بعد به آن برگردی.",
    "آرامش از حذف همهٔ دغدغه‌ها نمی‌آید؛ از مرتب‌کردن قدم بعدی شروع می‌شود.",
    "هر چیزی که امروز یاد می‌گیری، می‌تواند فردا انتخاب‌هایت را بهتر کند.",
    "برای ساختن چیزی ارزشمند، استمرار از هیجان لحظه‌ای قابل‌اعتمادتر است.",
    "به کارهای کوچکِ انجام‌شده نگاه کن؛ آن‌ها هم بخشی از مسیرند.",
    "اگر راه دشوار است، آن را به قدم‌هایی تقسیم کن که امروز شدنی‌اند.",
    "نوشتن، راهی برای بیرون‌آوردن فکرها از آشفتگی و دیدن دوبارهٔ آن‌هاست.",
    "به خودت فرصت اصلاح بده؛ لازم نیست نسخهٔ اول، نسخهٔ نهایی باشد.",
    "امروز را با یک کار معنادار شروع کن، نه با فهرست بلندِ کارهای عقب‌افتاده.",
    "پرسیدن یک سؤال دقیق، گاهی از عجله برای یافتن پاسخ مفیدتر است.",
    "هر بار که چیزی را بهتر سازمان می‌دهی، بخشی از انرژی آینده‌ات را آزاد می‌کنی.",
    "توجهت را به چیزی بده که می‌توانی تغییرش دهی؛ بقیه را فعلاً ثبت کن و کنار بگذار.",
    "استراحت و ادامه‌دادن دشمن هم نیستند؛ هر دو بخشی از یک مسیر پایدارند.",
    "یک تصمیم کوچکِ درست می‌تواند شروع تغییری بزرگ باشد.",
    "برای حل یک مسئله، اول آن را آن‌قدر روشن کن که بتوانی توضیحش بدهی.",
    "پیشرفت را فقط با سرعت نسنج؛ با روشن‌ترشدن مسیر هم بسنج.",
)


def offline_message(day: date | None = None) -> dict[str, str]:
    selected_day = day or date.today()
    index = selected_day.toordinal() % len(OFFLINE_MESSAGES)
    return {
        "text": OFFLINE_MESSAGES[index],
        "author": "یادآوری تألیفی روزنگار",
        "source_label": "پیام آفلاین روزنگار",
        "source_url": SOURCE_URL,
        "date": selected_day.isoformat(),
        "origin": "offline",
    }


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\u200e", "").replace("\u200f", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" \t\r\n\u200c|•*#;؛:،.ـ–—-")


def _valid_quote(text: str) -> bool:
    if not (24 <= len(text) <= 420):
        return False
    folded = text.casefold()
    blocked = (
        "ویکی‌گفتاورد", "صفحهٔ اصلی", "ویرایش", "این مقاله", "برای اطلاعات بیشتر",
        "این صفحه", "محتویات آزاد", "رده:", "پرش به", "جستجو",
    )
    return not any(term in folded for term in blocked) and any(ch.isalpha() for ch in text)


def extract_wikiquote_items(api_payload: dict[str, Any]) -> list[dict[str, str]]:
    """Extract individual Persian quotations from a MediaWiki plaintext response."""
    pages: list[dict[str, Any]] = []
    query = api_payload.get("query") or {}
    page_list = query.get("pages")
    if isinstance(page_list, list):
        pages = [page for page in page_list if isinstance(page, dict)]
    elif isinstance(page_list, dict):
        pages = [page for page in page_list.values() if isinstance(page, dict)]
    if not pages:
        raise ValueError("پاسخ ویکی‌گفتاورد شامل متن قابل‌خواندن نیست.")
    extract = "\n".join(str(page.get("extract") or "") for page in pages)
    if not extract.strip():
        raise ValueError("صفحهٔ منبع فعلاً متنی برای نمایش ندارد.")

    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    # Quoted Persian items usually appear as «text» followed by an author. Restrict
    # the selection to the quoted text to avoid importing surrounding page prose.
    pattern = re.compile(r"[«“\"]([^»”\"\n]{24,420})[»”\"]")
    for match in pattern.finditer(extract):
        quote = _clean(match.group(1))
        if not _valid_quote(quote):
            continue
        if quote in seen:
            continue
        seen.add(quote)
        tail = extract[match.end():].split("\n", 1)[0]
        tail = re.sub(r"\[[^\]]*\]", "", tail)
        tail = re.sub(r"\b\d{1,4}\b", "", tail)
        tail = _clean(tail)
        # Attribution is deliberately conservative. If the page does not clearly
        # put a short name immediately after the quotation, show the source label.
        if len(tail) > 72 or any(token in tail for token in ("ویکی", "صفحه", "بیشتر", "منبع")):
            tail = ""
        candidates.append({
            "text": quote,
            "author": tail or "ویکی‌گفتاورد فارسی",
            "source_label": SOURCE_LABEL,
            "source_url": SOURCE_URL,
            "origin": "wikiquote",
        })

    # Some pages use bare bullet lines. Treat them as a fallback, but do not turn
    # site navigation or prose into supposed quotations.
    if not candidates:
        for line in extract.splitlines():
            line = _clean(re.sub(r"^\s*(?:[*#•]+|\d+[.)])\s*", "", line))
            if not _valid_quote(line) or line in seen:
                continue
            if len(line) > 240:
                continue
            if any(phrase in line for phrase in ("صفحهٔ اصلی", "ویرایش", "این صفحه", "در پروژه‌های")):
                continue
            seen.add(line)
            candidates.append({
                "text": line,
                "author": "ویکی‌گفتاورد فارسی",
                "source_label": SOURCE_LABEL,
                "source_url": SOURCE_URL,
                "origin": "wikiquote",
            })

    if not candidates:
        raise ValueError("از متن منبع، نقل‌قول قابل‌استفاده‌ای پیدا نشد.")
    return candidates


def choose_daily_quote(api_payload: dict[str, Any], day: date | None = None) -> dict[str, str]:
    selected_day = day or date.today()
    items = extract_wikiquote_items(api_payload)
    # Adjacent days select adjacent entries from the current source list; thus the
    # choice changes daily as long as the source offers at least two usable quotes.
    selected = dict(items[selected_day.toordinal() % len(items)])
    selected["date"] = selected_day.isoformat()
    return selected


def parse_api_bytes(raw: bytes, day: date | None = None) -> dict[str, str]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("پاسخ سرویس الهام روز، JSON معتبر نیست.") from exc
    if not isinstance(payload, dict):
        raise ValueError("ساختار پاسخ سرویس الهام روز معتبر نیست.")
    return choose_daily_quote(payload, day)


def cache_key_for_day(day: date | None = None) -> str:
    return (day or date.today()).isoformat()
