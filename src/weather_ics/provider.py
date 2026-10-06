import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from .config import API_ROOT, LATITUDE, LOCATION_ID, LONGITUDE
from .database import connect, iso_utc, now_utc

LOG = logging.getLogger("weather_ics")


def google_get(endpoint: str, params: dict[str, str]) -> dict:
    key = os.getenv("GOOGLE_WEATHER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOOGLE_WEATHER_API_KEY is not set")
    query = {**params, "key": key}
    url = f"{API_ROOT}/{endpoint}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # The request URL contains the API key; never include it in a log message.
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Google Weather API returned HTTP {exc.code}: {detail}") from exc


def number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def quantity_mm(obj: object) -> float | None:
    if not isinstance(obj, dict):
        return None
    amount = number(obj.get("quantity"))
    if amount is None:
        return None
    if str(obj.get("unit", "MILLIMETERS")).upper() in ("INCHES", "INCH"):
        return amount * 25.4
    return amount


def ingest() -> None:
    issued_at = iso_utc(now_utc())
    params = {
        "location.latitude": str(LATITUDE),
        "location.longitude": str(LONGITUDE),
        "hours": "240",
        "pageSize": "24",
    }
    hours: list[dict] = []
    token: str | None = None
    for _ in range(12):
        page_params = dict(params)
        if token:
            page_params["pageToken"] = token
        payload = google_get("forecast/hours:lookup", page_params)
        hours.extend(payload.get("forecastHours", []))
        token = payload.get("nextPageToken")
        if not token:
            break

    daily_payload = google_get(
        "forecast/days:lookup",
        {
            "location.latitude": str(LATITUDE),
            "location.longitude": str(LONGITUDE),
            "days": "10",
        },
    )
    forecast_timezone = (daily_payload.get("timeZone") or {}).get("id")
    hourly_rows = []
    for item in hours:
        interval = item.get("interval") or {}
        valid_at, valid_end = interval.get("startTime"), interval.get("endTime")
        if not valid_at or not valid_end:
            continue
        precip = item.get("precipitation") or {}
        probability = precip.get("probability") or {}
        condition = item.get("weatherCondition") or {}
        temperature = item.get("temperature") or {}
        hourly_rows.append(
            (
                LOCATION_ID,
                issued_at,
                valid_at,
                valid_end,
                number(temperature.get("degrees")),
                number(probability.get("percent")),
                quantity_mm(precip.get("qpf")),
                int(item["cloudCover"]) if item.get("cloudCover") is not None else None,
                condition.get("type"),
                (condition.get("description") or {}).get("text"),
                int(bool(item.get("isDaytime"))) if item.get("isDaytime") is not None else None,
            )
        )

    daily_rows = []
    for item in daily_payload.get("forecastDays", []):
        display_date = item.get("displayDate") or {}
        try:
            local_date = f"{int(display_date['year']):04d}-{int(display_date['month']):02d}-{int(display_date['day']):02d}"
        except (KeyError, TypeError, ValueError):
            continue
        daily_rows.append(
            (
                LOCATION_ID,
                issued_at,
                local_date,
                forecast_timezone,
                number((item.get("minTemperature") or {}).get("degrees")),
                number((item.get("maxTemperature") or {}).get("degrees")),
            )
        )

    with connect() as db:
        db.executemany(
            """INSERT OR REPLACE INTO hourly_forecasts
               (location, issued_at, valid_at, valid_end, temperature_c,
                precipitation_probability, precipitation_mm, cloud_cover,
                condition_type, condition_text, is_daytime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            hourly_rows,
        )
        db.executemany(
            """INSERT OR REPLACE INTO daily_forecasts
               (location, issued_at, local_date, time_zone, low_c, high_c)
               VALUES (?, ?, ?, ?, ?, ?)""",
            daily_rows,
        )
        db.execute(
            """INSERT INTO service_state (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (f"last_successful_refresh:{LOCATION_ID}", issued_at),
        )
    LOG.info("Stored %d hourly and %d daily forecasts", len(hourly_rows), len(daily_rows))
    from .calendar_feed import invalidate_cache

    invalidate_cache()
