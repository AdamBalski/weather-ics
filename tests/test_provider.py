import io
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from weather_ics import database, provider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path_patch = patch.object(database, "DB_PATH", str(Path(self.temp_dir.name) / "weather.sqlite3"))
        self.db_path_patch.start()
        database.initialize_db()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_daily_request_fetches_ten_days_and_stores_daytime_precipitation(self):
        daily_payload = {
            "timeZone": {"id": "Europe/Warsaw"},
            "nextPageToken": "unexpected-token",
            "forecastDays": [
                {
                    "displayDate": {"year": 2026, "month": 10, "day": 6},
                    "minTemperature": {"degrees": 8},
                    "maxTemperature": {"degrees": 17},
                    "daytimeForecast": {
                        "precipitation": {
                            "probability": {"percent": 42},
                            "qpf": {"quantity": 3.25, "unit": "MILLIMETERS"},
                        }
                    },
                }
            ],
        }
        with (
            patch.object(provider, "google_get", side_effect=[{"forecastHours": []}, daily_payload]) as request,
            self.assertLogs(provider.LOG, level="ERROR") as captured,
        ):
            provider.ingest()

        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].args[0], "forecast/days:lookup")
        self.assertEqual(request.call_args_list[1].args[1]["days"], "10")
        self.assertEqual(request.call_args_list[1].args[1]["pageSize"], "10")
        self.assertNotIn("pageToken", request.call_args_list[1].args[1])
        self.assertIn("ignoring it", captured.output[0])
        with database.connect() as db:
            row = db.execute(
                "SELECT daytime_precipitation_probability, daytime_precipitation_mm FROM daily_forecasts"
            ).fetchone()
        self.assertEqual(row["daytime_precipitation_probability"], 42)
        self.assertEqual(row["daytime_precipitation_mm"], 3.25)

    def test_google_calls_are_counted_by_endpoint_and_utc_hour(self):
        started_at = datetime(2026, 10, 6, 12, 34, tzinfo=timezone.utc)
        with (
            patch.dict(os.environ, {"GOOGLE_WEATHER_API_KEY": "test-key"}),
            patch.object(provider, "now_utc", return_value=started_at),
            patch.object(provider.urllib.request, "urlopen", return_value=io.BytesIO(b'{"ok":true}')),
        ):
            self.assertEqual(provider.google_get("forecast/hours:lookup", {}), {"ok": True})

        with (
            patch.dict(os.environ, {"GOOGLE_WEATHER_API_KEY": "test-key"}),
            patch.object(provider, "now_utc", return_value=started_at),
            patch.object(
                provider.urllib.request,
                "urlopen",
                side_effect=urllib.error.HTTPError("https://weather.googleapis.com", 403, "Forbidden", None, io.BytesIO(b"{}")),
            ),
        ):
            with self.assertRaises(RuntimeError):
                provider.google_get("forecast/hours:lookup", {})

        with database.connect() as db:
            row = db.execute(
                """SELECT hour_start, calls, successes, failures FROM google_api_call_metrics
                   WHERE call_type='forecast/hours:lookup'"""
            ).fetchone()
        self.assertEqual(row["hour_start"], "2026-10-06T12:00:00+00:00")
        self.assertEqual((row["calls"], row["successes"], row["failures"]), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()
