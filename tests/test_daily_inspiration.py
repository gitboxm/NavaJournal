import json
from datetime import date
import unittest

from nava_journal.daily_inspiration import (
    OFFLINE_MESSAGES,
    SOURCE_LABEL,
    SOURCE_URL,
    choose_daily_quote,
    extract_wikiquote_items,
    offline_message,
    parse_api_bytes,
)


class DailyInspirationTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "query": {
                "pages": [{
                    "pageid": 1,
                    "title": "گفتاورد",
                    "extract": (
                        "گفتاورد\n"
                        "«برای رسیدن به مقصد، نخست باید قدم اول را آگاهانه برداشت.»\n"
                        "«دانایی زمانی ارزشمند است که در تصمیم و عمل روشن شود.»\n"
                        "«صبوری و پیوستگی، راه دشوار را به مسیرهای شدنی تقسیم می‌کنند.»\n"
                    ),
                }]
            }
        }

    def test_extracts_usable_quotes_and_source_metadata(self):
        items = extract_wikiquote_items(self.payload)
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(all(len(item["text"]) >= 24 for item in items))
        self.assertEqual(items[0]["source_label"], SOURCE_LABEL)
        self.assertEqual(items[0]["source_url"], SOURCE_URL)
        self.assertEqual(items[0]["origin"], "wikiquote")

    def test_selected_quote_changes_by_day_and_has_date(self):
        first_day = date(2026, 10, 29)
        first = choose_daily_quote(self.payload, first_day)
        second = choose_daily_quote(self.payload, date(2026, 10, 30))
        self.assertNotEqual(first["text"], second["text"])
        self.assertEqual(first["date"], "2026-10-29")
        self.assertEqual(second["date"], "2026-10-30")

    def test_json_parser_rejects_invalid_response(self):
        with self.assertRaises(ValueError):
            parse_api_bytes(b"not json", date(2026, 10, 29))

    def test_offline_reminders_are_original_and_change_daily(self):
        first = offline_message(date(2026, 10, 29))
        second = offline_message(date(2026, 10, 30))
        self.assertNotEqual(first["text"], second["text"])
        self.assertEqual(first["origin"], "offline")
        self.assertEqual(first["author"], "یادآوری تألیفی روزنگار")
        self.assertGreaterEqual(len(OFFLINE_MESSAGES), 7)


if __name__ == "__main__":
    unittest.main()
