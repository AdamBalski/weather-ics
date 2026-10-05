import os


API_ROOT = "https://weather.googleapis.com/v1"
DB_PATH = os.getenv("DATABASE_PATH", "/data/weather.sqlite3")
LATITUDE = float(os.getenv("LOCATION_LATITUDE", "50.0647"))
LONGITUDE = float(os.getenv("LOCATION_LONGITUDE", "19.9450"))
DEFAULT_TIMEZONE = "UTC"
PORT = int(os.getenv("PORT", "8080"))
SOURCE_CREDIT = "Source: Includes weather data from Google."
REFRESH_SECONDS = 4 * 60 * 60
LOCATION_ID = f"{LATITUDE:.6f},{LONGITUDE:.6f}"
