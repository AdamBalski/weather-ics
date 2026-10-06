import logging
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .calendar_feed import get_calendar, invalidate_cache
from .config import DEFAULT_TIMEZONE, PORT, REFRESH_SECONDS
from .database import cleanup, initialize_db
from .provider import ingest

LOG = logging.getLogger("weather_ics")
INDEX_HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"
SUPPORTED_TIMEZONES = ["UTC", *sorted(available_timezones() - {"UTC"}, key=str.casefold)]


def maintenance_loop() -> None:
    next_refresh = 0.0
    next_cleanup = 0.0
    while True:
        now = time.time()
        if now >= next_refresh:
            try:
                ingest()
                cleanup()
                invalidate_cache()
            except Exception:
                LOG.exception("Forecast refresh failed")
            next_refresh = now + REFRESH_SECONDS
        if now >= next_cleanup:
            try:
                cleanup()
                invalidate_cache()
            except Exception:
                LOG.exception("Forecast cleanup failed")
            next_cleanup = now + 24 * 60 * 60
        time.sleep(30)


class Handler(BaseHTTPRequestHandler):
    server_version = "WeatherCalendar/1.0"

    def send_text(self, status: int, message: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            page = INDEX_HTML.read_text(encoding="utf-8")
            return self.send_text(200, page, "text/html; charset=utf-8")
        if parsed.path == "/supportedTimezones":
            return self.send_text(200, json.dumps(SUPPORTED_TIMEZONES), "application/json; charset=utf-8")
        if parsed.path == "/health":
            return self.send_text(200, "ok\n")
        if parsed.path != "/calendar.ics":
            return self.send_text(404, "Not found\n")
        params = parse_qs(parsed.query, keep_blank_values=True)
        fmt = params.get("format", ["raw"])[0]
        if fmt not in ("raw", "html", "compact"):
            return self.send_text(400, "format must be raw, html, or compact\n")
        tz_name = params.get("tz", [DEFAULT_TIMEZONE])[0]
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            return self.send_text(400, "tz must be a valid IANA timezone, such as Europe/Warsaw\n")
        try:
            body = get_calendar(tz_name, fmt)
        except RuntimeError as exc:
            return self.send_text(503, f"{exc}\n")
        except Exception:
            LOG.exception("Could not render calendar")
            return self.send_text(500, "Could not render calendar\n")
        self.send_text(200, body, "text/calendar; charset=utf-8")

    def log_message(self, fmt: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    initialize_db()
    threading.Thread(target=maintenance_loop, name="weather-maintenance", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    LOG.info("Listening on port %d", PORT)
    server.serve_forever()
