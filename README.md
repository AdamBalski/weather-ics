# Weather Calendar Feed

A small SQLite-backed service that publishes one all-day weather event per local date as an iCalendar feed, using the Google Maps Platform Weather API.

## Run with Docker Compose

Enable the Weather API and create an API key in Google Cloud. Export the key in the shell where Compose will run, then start the service:

```sh
export GOOGLE_WEATHER_API_KEY="your-key"
docker compose up --build -d
```

The key is interpolated by Docker Compose at startup and passed to the application container. Do not commit it to `.env`, source control, or the image. To change the single configured location, export `LOCATION_LATITUDE` and `LOCATION_LONGITUDE`; the default is Kraków.

The service immediately fetches hourly (240 hour) and daily (10 day) forecasts, then refreshes every four hours. It runs database cleanup daily and also cleans expired rows after each successful refresh. SQLite is stored in the persistent `weather-data` Compose volume. UTC is the default timezone; set `tz` in the feed URL to use another IANA timezone.

## Feed

```text
http://localhost:8080/calendar.ics
http://localhost:8080/calendar.ics?tz=Europe%2FWarsaw
http://localhost:8080/calendar.ics?tz=Europe%2FWarsaw&format=html
```

The root URL (`/`) describes the service and provides read-only URLs with copy buttons for both feed formats. `format` may be omitted or set to `raw`; `html` selects an HTML table in the iCalendar description. Unknown formats and invalid IANA timezones return HTTP 400. `/health` is available for container health checks.

`GET /supportedTimezones` returns the full timezone list available to this service, which the root page uses to populate its timezone dropdown.


The feed includes local dates starting two calendar days before today, where stored forecast hours are available. It stores forecast issue time separately from each hour's valid time and chooses the latest stored snapshot for each valid hour. Missing values appear as an em dash. The daily endpoint supplies low/high values when its timezone matches the requested feed timezone; otherwise, the service calculates them from that local date's hourly forecasts. Rain risk combines the available hourly precipitation probabilities for local intervals beginning 08:00 through 19:00 using the product formula in the product plan.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_WEATHER_API_KEY` | required | Google Weather API credential |
| `LOCATION_LATITUDE` | `50.0647` | Configured location latitude |
| `LOCATION_LONGITUDE` | `19.9450` | Configured location longitude |
| `PORT` | `8080` | Host port published by Compose |

## GitHub Actions deployment

The **Test** workflow compiles the source and runs the unit and route tests on pull requests and pushes to `main`. After a successful `main` push, **Build** publishes an ARM64 image to GHCR with the commit SHA and `latest` tags.

**Deploy** is a manual workflow. Configure these GitHub Actions secrets:

| Secret | Value |
| --- | --- |
| `SSH_PRIVATE_KEY` | Private key authorized on the deployment host |
| `REMOTE_HOST` | Hostname or IP of the deployment host |
| `REMOTE_USERNAME` | SSH username |
| `REMOTE_PORT` | SSH port; optional, defaults to `22` |
| `GOOGLE_WEATHER_API_KEY` | Google Weather API key |

The remote host must have `/home/<REMOTE_USERNAME>/infra/compose/weather-ics.yml` and a versions file at `/home/<REMOTE_USERNAME>/infra/compose/versions/weather-ics`. The compose file should reference the GHCR image using `WEATHER_ICS_VERSION`, pass through `GOOGLE_WEATHER_API_KEY` with Compose variable interpolation, expose the service behind your proxy, and persist `/data`. Deploy streams the key over its SSH connection to the remote Compose process, without adding it to the command line or a Compose file. The workflow writes the selected ref's commit SHA to the versions file and runs `docker compose up -d --wait`.
