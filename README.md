# Weather Calendar Feed

A small SQLite-backed service that publishes one all-day weather event per local date as an iCalendar feed, using the Google Maps Platform Weather API.

## Run with Docker Compose

Enable the Weather API and create an API key in Google Cloud. Export the key in the shell where Compose will run, then start the service using the development override (which builds from the local source):

```sh
export GOOGLE_WEATHER_API_KEY="your-key"
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

The key is interpolated by Docker Compose at startup and passed to the application container. Do not commit it to `.env`, source control, or the image. To change the single configured location, export `LOCATION_LATITUDE` and `LOCATION_LONGITUDE`; the default is Kraków.

The base `docker-compose.yml` pulls the published GHCR image. The development override builds from the local source. The service fetches hourly (240 hour) and daily (10 day) forecasts on startup only if there is no successful refresh in the last four hours. Otherwise it waits until four hours have elapsed since that refresh, then continues on the same interval. It runs database cleanup daily and after each successful refresh. SQLite is stored in the persistent `weather-data` Compose volume. UTC is the default timezone; set `tz` in the feed URL to use another IANA timezone.

## Feed

```text
http://localhost:8080/calendar.ics
http://localhost:8080/calendar.ics?tz=Europe%2FWarsaw
http://localhost:8080/calendar.ics?tz=Europe%2FWarsaw&format=compact
http://localhost:8080/calendar.ics?tz=Europe%2FWarsaw&format=html
```

The root URL (`/`) describes the service and provides read-only URLs with copy buttons. `format` may be omitted or set to `raw`; `compact` uses clock emoji for rain probability and cloud cover, and `html` selects an HTML table in the iCalendar description. In compact mode, 🕛 means 0% and 🕚 represents approximately 92–100%; intermediate values round to the nearest hour step. Unknown formats and invalid IANA timezones return HTTP 400. `/health` is available for container health checks.

`GET /supportedTimezones` returns the full timezone list available to this service, which the root page uses to populate its timezone dropdown.


The feed includes local dates starting two calendar days before today, where stored forecast hours are available. It stores forecast issue time separately from each hour's valid time and chooses the latest stored snapshot for each valid hour. Missing values appear as an em dash. The daily endpoint supplies low/high values when its timezone matches the requested feed timezone; otherwise, the service calculates them from that local date's hourly forecasts. Rain risk combines the available hourly precipitation probabilities for local intervals beginning 08:00 through 19:00 using the product formula in the product plan.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_WEATHER_API_KEY` | required | Google Weather API credential |
| `LOCATION_LATITUDE` | `50.0647` | Configured location latitude |
| `LOCATION_LONGITUDE` | `19.9450` | Configured location longitude |
| `PORT` | `8080` | Host port published by Compose |
| `WEATHER_ICS_VERSION` | `latest` | GHCR image tag; Deploy sets this to the selected commit SHA |
