# Configuration

This project uses two local JSON files:

- `secrets.json`: private HA credentials.
- `config.json`: dashboard behavior, entities, layout/localization options.

## `secrets.json`

Example:

```json
{
  "ha_url": "http://192.168.1.X:8123",
  "ha_token": "eyJhbGciOi..."
}
```

Get token from Home Assistant: Profile -> Long-lived access tokens.

## `config.json`

Start from `config.json.example`.

### Required keys

- `weather_entity`: HA weather entity (example `weather.forecast_home`).
- `rooms`: array of room tiles.

Room object fields:

- `name`: display label.
- `icon`: one of `kitchen`, `livingroom`, `bedroom`, `childroom`, `bathroom`, `laundry`, `storage`.
- `temp`: temperature sensor entity id.
- `hum`: humidity sensor entity id.

### Optional weather/sun fields

- `outdoor_temp`
- `outdoor_hum`
- `outdoor_uv`
- `outdoor_aqi`
- `outdoor_pm25`
- `sun_entity` (default `sun.sun`)

### Header/date options

- `header_title` (default `HOUSE`)
- `show_clock` (`true`/`false`)
- `header_weekday_format` (`full` or `abbr`)
- `header_month_format` (`full` or `abbr`)
- `forecast_weekday_format` (`full` or `abbr`)

### Quotes/footer options

- `footer_daily_quote` (`true` to fetch quote of the day)
- `quote_api_url` (default `https://zenquotes.io/api/today`)
- `quote_cache_file` (default `/tmp/epaper_daily_quote.json`)
- `footer_quote` / `footer_source` (manual fallback)

### Clock daemon / refresh options

- `clock_partial_refresh` (enable partial refresh where available)
- `clock_partial_fullscreen` (`true` = fullscreen partial for data updates, `false` = no partial on data updates; data ticks are refreshed with full update only when data changed, to reduce ghosting/fading)
- `clock_daemon_interval_sec` (tick interval, default `60`)
- `clock_daemon_data_every_min` (data refresh interval, default `10`)
- `clock_daemon_full_every_ticks` (force full refresh every N display ticks, not minutes)
- `clock_daemon_full_every` (deprecated alias of `clock_daemon_full_every_ticks`)

## Notes on HA forecast

Many HA weather entities expose `state` but keep `attributes.forecast` empty.
This project calls `weather/get_forecasts` service and caches intraday min/max data.
If you see missing forecast blocks, verify service response first.
