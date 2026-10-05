import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from weather_ics import calendar_feed


class CalendarFeedTests(unittest.TestCase):
    def test_render_description_includes_hourly_data_and_attribution(self):
        row = {
            "valid_at": "2026-05-03T08:00:00Z",
            "condition_type": "RAIN",
            "condition_text": "Light rain",
            "temperature_c": 12.0,
            "precipitation_probability": 40.0,
            "precipitation_mm": 1.25,
            "cloud_cover": 80,
        }

        raw = calendar_feed.render_description([row], timezone.utc, html_mode=False)
        html = calendar_feed.render_description([row], timezone.utc, html_mode=True)

        self.assertIn("HH", raw)
        self.assertIn("🌧️08", raw)
        self.assertIn("12°C", raw)
        self.assertIn("40%", raw)
        self.assertIn("CC% = cloud cover", raw)
        self.assertIn(calendar_feed.SOURCE_CREDIT, raw)
        self.assertIn("<table", html)
        self.assertIn("<td>🌧️08</td><td>12°C</td><td>40%</td>", html)
        self.assertIn("CC% = cloud cover", html)
        self.assertIn(calendar_feed.SOURCE_CREDIT, html)

    def test_calendar_calculates_range_and_combined_rain_risk(self):
        rows = []
        for hour in range(8, 20):
            rows.append(
                {
                    "valid_at": f"2026-05-03T{hour:02d}:00:00Z",
                    "condition_type": "RAIN",
                    "condition_text": "Rain",
                    "temperature_c": float(hour - 5),
                    "precipitation_probability": 10.0,
                    "precipitation_mm": 0.5,
                    "cloud_cover": 80,
                    "is_daytime": 1,
                }
            )

        with (
            patch.object(calendar_feed, "latest_hourly", return_value=rows),
            patch.object(calendar_feed, "latest_daily", return_value=[]),
            patch.object(calendar_feed, "now_utc", return_value=datetime(2026, 5, 3, 12, tzinfo=timezone.utc)),
        ):
            result = calendar_feed.build_calendar("UTC", html_mode=False)

        # 1 - (1 - 0.1)^12 = 71.76%, rounded to 72%.
        self.assertIn("SUMMARY:🌧️⬇️3°C⬆️14°C<72%>", result)
        self.assertIn("DTSTART;VALUE=DATE:20260503", result)
        self.assertIn("DTEND;VALUE=DATE:20260504", result)
        self.assertEqual(result.count("BEGIN:VEVENT"), 1)

    def test_feed_cache_is_keyed_by_timezone_and_format(self):
        calendar_feed.invalidate_cache()
        with patch.object(calendar_feed, "build_calendar", side_effect=["raw utc", "html utc", "raw warsaw"]) as build:
            self.assertEqual(calendar_feed.get_calendar("UTC", False), "raw utc")
            self.assertEqual(calendar_feed.get_calendar("UTC", False), "raw utc")
            self.assertEqual(calendar_feed.get_calendar("UTC", True), "html utc")
            self.assertEqual(calendar_feed.get_calendar("Europe/Warsaw", False), "raw warsaw")
        self.assertEqual(build.call_count, 3)
        calendar_feed.invalidate_cache()


if __name__ == "__main__":
    unittest.main()
