import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from weather_ics import server


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_root_serves_landing_page(self):
        with urlopen(f"{self.base}/") as response:
            page = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Weather Calendar Feed", page)
        self.assertIn("Copy URL", page)

    def test_supported_timezones_returns_utc_first(self):
        with urlopen(f"{self.base}/supportedTimezones") as response:
            names = json.load(response)
            content_type = response.headers["Content-Type"]
        self.assertEqual(names[0], "UTC")
        self.assertIn("Europe/Warsaw", names)
        self.assertIn("application/json", content_type)

    def test_calendar_route_passes_timezone_and_format(self):
        with patch.object(server, "get_calendar", return_value="BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n") as render:
            with urlopen(f"{self.base}/calendar.ics?tz=Europe%2FWarsaw&format=html") as response:
                body = response.read().decode("utf-8")
                content_type = response.headers["Content-Type"]
        render.assert_called_once_with("Europe/Warsaw", "html")
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("text/calendar", content_type)

    def test_invalid_timezone_returns_bad_request(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base}/calendar.ics?tz=Not%2FAZone")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_unknown_format_returns_bad_request(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base}/calendar.ics?format=xml")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_compact_format_is_accepted(self):
        with patch.object(server, "get_calendar", return_value="BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n") as render:
            with urlopen(f"{self.base}/calendar.ics?format=compact") as response:
                body = response.read().decode("utf-8")
        render.assert_called_once_with("UTC", "compact")
        self.assertIn("BEGIN:VCALENDAR", body)

    def test_refresh_delay_uses_remaining_configured_interval(self):
        now = datetime(2026, 5, 3, 12, tzinfo=timezone.utc)
        last_refresh = now - timedelta(hours=3)
        self.assertEqual(server.refresh_delay(last_refresh, now), 60 * 60)
        self.assertEqual(server.refresh_delay(now - timedelta(hours=5), now), 0)
        self.assertEqual(server.refresh_delay(None, now), 0)


if __name__ == "__main__":
    unittest.main()
