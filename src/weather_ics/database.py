from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from .config import DB_PATH, LOCATION_ID


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def initialize_db() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS hourly_forecasts (
                id INTEGER PRIMARY KEY,
                location TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                valid_at TEXT NOT NULL,
                valid_end TEXT NOT NULL,
                temperature_c REAL,
                precipitation_probability REAL,
                precipitation_mm REAL,
                cloud_cover INTEGER,
                condition_type TEXT,
                condition_text TEXT,
                is_daytime INTEGER,
                UNIQUE(location, issued_at, valid_at)
            );
            CREATE INDEX IF NOT EXISTS hourly_valid_idx
                ON hourly_forecasts(location, valid_at, issued_at);
            CREATE TABLE IF NOT EXISTS daily_forecasts (
                id INTEGER PRIMARY KEY,
                location TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                local_date TEXT NOT NULL,
                time_zone TEXT,
                low_c REAL,
                high_c REAL,
                daytime_precipitation_probability REAL,
                daytime_precipitation_mm REAL,
                UNIQUE(location, issued_at, local_date)
            );
            CREATE INDEX IF NOT EXISTS daily_date_idx
                ON daily_forecasts(location, local_date, issued_at);
            CREATE TABLE IF NOT EXISTS service_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS google_api_call_metrics (
                hour_start TEXT NOT NULL,
                call_type TEXT NOT NULL,
                calls INTEGER NOT NULL DEFAULT 0,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (hour_start, call_type)
            );
            """
        )
        # Keep existing Compose volumes usable when upgrading from the first schema.
        daily_columns = {row["name"] for row in db.execute("PRAGMA table_info(daily_forecasts)")}
        if "time_zone" not in daily_columns:
            db.execute("ALTER TABLE daily_forecasts ADD COLUMN time_zone TEXT")
        for column in ("daytime_precipitation_probability", "daytime_precipitation_mm"):
            if column not in daily_columns:
                db.execute(f"ALTER TABLE daily_forecasts ADD COLUMN {column} REAL")


def latest_successful_refresh() -> datetime | None:
    state_key = f"last_successful_refresh:{LOCATION_ID}"
    with connect() as db:
        row = db.execute(
            "SELECT value FROM service_state WHERE key=?", (state_key,)
        ).fetchone()
        if row:
            return datetime.fromisoformat(row["value"])

        # Use existing forecast snapshots when upgrading a database created
        # before successful refresh times were stored explicitly.
        row = db.execute(
            """SELECT MAX(issued_at) AS issued_at FROM (
                   SELECT issued_at FROM hourly_forecasts WHERE location=?
                   UNION ALL
                   SELECT issued_at FROM daily_forecasts WHERE location=?
               )""",
            (LOCATION_ID, LOCATION_ID),
        ).fetchone()
        return datetime.fromisoformat(row["issued_at"]) if row and row["issued_at"] else None


def record_google_api_call(call_type: str, started_at: datetime, succeeded: bool) -> None:
    hour_start = iso_utc(started_at.replace(minute=0, second=0, microsecond=0))
    with connect() as db:
        db.execute(
            """INSERT INTO google_api_call_metrics
                   (hour_start, call_type, calls, successes, failures)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(hour_start, call_type) DO UPDATE SET
                   calls=calls+1,
                   successes=successes+excluded.successes,
                   failures=failures+excluded.failures""",
            (hour_start, call_type, int(succeeded), int(not succeeded)),
        )


def cleanup() -> None:
    now = now_utc()
    lower = iso_utc(now - timedelta(hours=72))
    upper = iso_utc(now + timedelta(hours=240))
    lower_day = (now - timedelta(hours=72)).date().isoformat()
    upper_day = (now + timedelta(hours=240)).date().isoformat()
    with connect() as db:
        db.execute(
            "DELETE FROM hourly_forecasts WHERE location=? AND (valid_at < ? OR valid_at > ?)",
            (LOCATION_ID, lower, upper),
        )
        db.execute(
            "DELETE FROM daily_forecasts WHERE location=? AND (local_date < ? OR local_date > ?)",
            (LOCATION_ID, lower_day, upper_day),
        )


def latest_hourly(lower: str, upper: str) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            """SELECT h.* FROM hourly_forecasts h
               JOIN (SELECT valid_at, MAX(issued_at) AS newest FROM hourly_forecasts
                     WHERE location=? AND valid_at >= ? AND valid_at <= ? GROUP BY valid_at) latest
                 ON h.valid_at=latest.valid_at AND h.issued_at=latest.newest
               WHERE h.location=? ORDER BY h.valid_at""",
            (LOCATION_ID, lower, upper, LOCATION_ID),
        ).fetchall()


def latest_daily() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            """SELECT d.* FROM daily_forecasts d JOIN
               (SELECT local_date, MAX(issued_at) AS newest FROM daily_forecasts
                WHERE location=? GROUP BY local_date) latest
               ON d.local_date=latest.local_date AND d.issued_at=latest.newest
               WHERE d.location=?""",
            (LOCATION_ID, LOCATION_ID),
        ).fetchall()
