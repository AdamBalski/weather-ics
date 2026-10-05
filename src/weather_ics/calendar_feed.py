import html
import math
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import LATITUDE, LONGITUDE, SOURCE_CREDIT
from .database import iso_utc, latest_daily, latest_hourly, now_utc

FEED_CACHE: dict[tuple[str, bool], tuple[float, str]] = {}
CACHE_LOCK = threading.Lock()


def invalidate_cache() -> None:
    with CACHE_LOCK:
        FEED_CACHE.clear()


def display_number(value: float | None, precision: int = 0) -> str:
    return "—" if value is None else f"{value:.{precision}f}"


def icon_for(row, local_hour: int) -> str:
    kind = (row["condition_type"] or "").upper()
    if "THUNDERSTORM" in kind:
        return "⛈️"
    if "SNOW" in kind or "SLEET" in kind:
        return "🌨️"
    if any(word in kind for word in ("RAIN", "DRIZZLE", "SHOWER")):
        return "🌧️"
    if "FOG" in kind or "HAZE" in kind:
        return "🌫️"
    cover = row["cloud_cover"]
    if cover is None or cover < 20:
        return "🌙" if local_hour < 6 or local_hour >= 20 else "☀️"
    if cover < 65:
        return "🌤️" if local_hour < 6 or local_hour >= 20 else "🌥️"
    return "☁️"


def escape_ics(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\r\n", r"\n").replace("\n", r"\n")


def fold_ics(line: str) -> str:
    parts: list[str] = []
    current = ""
    octets = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if octets + size > 74:
            parts.append(current)
            current = " "
            octets = 1
        current += char
        octets += size
    parts.append(current)
    return "\r\n".join(parts)


def render_description(rows, tz: ZoneInfo, html_mode: bool) -> str:
    headers = ("HH", "T", "R%", "mm", "CC%")
    data = []
    for row in rows:
        start = datetime.fromisoformat(row["valid_at"].replace("Z", "+00:00")).astimezone(tz)
        data.append(
            (
                f"{icon_for(row, start.hour)}{start:%H}",
                f"{display_number(row['temperature_c'])}°C" if row["temperature_c"] is not None else "—",
                f"{display_number(row['precipitation_probability'])}%" if row["precipitation_probability"] is not None else "—",
                display_number(row["precipitation_mm"], 1),
                f"{display_number(row['cloud_cover'])}%" if row["cloud_cover"] is not None else "—",
            )
        )
    legend = "HH = local hour; T = temperature; R% = precipitation probability; mm = expected precipitation; CC% = cloud cover."
    if html_mode:
        out = ['<table border="1"><thead><tr>']
        out.extend(f"<th>{html.escape(header)}</th>" for header in headers)
        out.append("</tr></thead><tbody>")
        for row in data:
            out.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>")
        out.append("</tbody></table><p>" + html.escape(legend) + "</p><p>" + html.escape(SOURCE_CREDIT) + "</p>")
        return "".join(out)
    widths = [max(len(headers[i]), *(len(row[i]) for row in data)) if data else len(headers[i]) for i in range(len(headers))]
    lines = ["  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))).rstrip()]
    lines.extend("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))).rstrip() for row in data)
    lines.extend(("", legend))
    lines.extend(("", SOURCE_CREDIT))
    return "\n".join(lines)


def build_calendar(tz_name: str, html_mode: bool) -> str:
    tz = ZoneInfo(tz_name)
    now = now_utc()
    hourly = latest_hourly(iso_utc(now - timedelta(hours=72)), iso_utc(now + timedelta(hours=240)))
    daily = latest_daily()
    by_day: dict[str, list] = {}
    for row in hourly:
        instant = datetime.fromisoformat(row["valid_at"].replace("Z", "+00:00"))
        by_day.setdefault(instant.astimezone(tz).date().isoformat(), []).append(row)
    daily_map = {row["local_date"]: row for row in daily if row["time_zone"] == tz_name}
    if not by_day:
        raise RuntimeError("No forecast data is available yet; try again shortly")

    first_date = now.astimezone(tz).date() - timedelta(days=2)
    day_keys = sorted(key for key in by_day if date.fromisoformat(key) >= first_date)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Weather ICS//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for day_key in day_keys:
        rows = by_day[day_key]
        daily_row = daily_map.get(day_key)
        temps = [row["temperature_c"] for row in rows if row["temperature_c"] is not None]
        low = daily_row["low_c"] if daily_row and daily_row["low_c"] is not None else (min(temps) if temps else None)
        high = daily_row["high_c"] if daily_row and daily_row["high_c"] is not None else (max(temps) if temps else None)
        probabilities = []
        for row in rows:
            local = datetime.fromisoformat(row["valid_at"].replace("Z", "+00:00")).astimezone(tz)
            if 8 <= local.hour <= 19 and row["precipitation_probability"] is not None:
                probabilities.append(max(0.0, min(100.0, row["precipitation_probability"])) / 100.0)
        rain = round(100 * (1 - math.prod(1 - probability for probability in probabilities))) if probabilities else None
        daytime_rows = [row for row in rows if row["is_daytime"] == 1]
        candidates = daytime_rows or rows
        priority = {"THUNDERSTORM": 5, "SNOW": 4, "SLEET": 4, "RAIN": 3, "DRIZZLE": 3, "FOG": 2}

        def severity(row) -> int:
            kind = (row["condition_type"] or "").upper()
            return max((value for needle, value in priority.items() if needle in kind), default=0)

        significant = max(candidates, key=severity)
        local_hour = datetime.fromisoformat(significant["valid_at"].replace("Z", "+00:00")).astimezone(tz).hour
        title = f"{icon_for(significant, local_hour)}⬇️{display_number(low)}°C⬆️{display_number(high)}°C<{display_number(rain)}%>"
        day = date.fromisoformat(day_key)
        next_day = day + timedelta(days=1)
        description = render_description(rows, tz, html_mode)
        format_id = "html" if html_mode else "raw"
        uid = f"{day_key}-{LATITUDE:.6f}-{LONGITUDE:.6f}-{format_id}@weather-ics"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{next_day.strftime('%Y%m%d')}",
                f"SUMMARY:{escape_ics(title)}",
                f"DESCRIPTION:{escape_ics(description)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics(line) for line in lines) + "\r\n"


def get_calendar(tz_name: str, html_mode: bool) -> str:
    cache_key = (tz_name, html_mode)
    with CACHE_LOCK:
        cached = FEED_CACHE.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]
    body = build_calendar(tz_name, html_mode)
    with CACHE_LOCK:
        FEED_CACHE[cache_key] = (time.time() + 60 * 60, body)
    return body
