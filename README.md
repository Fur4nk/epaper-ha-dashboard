# e-Paper Dashboard — Setup

Home Assistant dashboard for Waveshare 7.5" V2 e-Paper display (800×480) in portrait mode.  
Displays indoor room temperature/humidity, outdoor weather, and 4-day forecast.

## File structure

```
epaper-dashboard/
├── ha_epaper_dashboard.py      # main script (safe to commit)
├── config.json.example         # rooms/entities template (safe to commit)
├── config.json                 # your configuration (safe to commit, no secrets)
├── secrets.json.example        # credentials template (safe to commit)
└── secrets.json                # your HA credentials (DO NOT commit)
```

## 1. Dependencies

```bash
sudo apt install python3-pil python3-numpy python3-rpi.gpio python3-spidev
git clone https://github.com/waveshare/e-Paper ~/src/e-Paper
```

You can point the script to Waveshare library path with:

- CLI: `--epd-lib-path /path/to/e-Paper/RaspberryPi_JetsonNano/python/lib`
- env: `EPD_LIB_PATH=/path/to/e-Paper/RaspberryPi_JetsonNano/python/lib`

## 2. Setup

```bash
cd /home/pi
git clone <your-repo> epaper-dashboard
cd epaper-dashboard

cp secrets.json.example secrets.json
cp config.json.example config.json

nano secrets.json   # HA credentials (gitignored)
nano config.json    # rooms and entities
```

## 3. secrets.json

```json
{
    "ha_url": "http://192.168.1.X:8123",
    "ha_token": "eyJhbGciOi..."
}
```

To create a Long-Lived Access Token:  
HA → User profile → Long-lived access tokens → Create token

## 4. config.json

Available room icons: `kitchen`, `livingroom`, `bedroom`, `childroom`, `bathroom`, `laundry`, `storage`

Supported weather condition names (for icon assets):  
`sunny`, `clear-night`, `partlycloudy`, `cloudy`, `rainy`, `pouring`, `snowy`, `snowy-rainy`, `fog`, `hail`, `lightning`, `lightning-rainy`, `windy`, `windy-variant`, `exceptional`

Optional footer quote fields:

- `footer_daily_quote` (`true` = nuova frase ogni giorno da ZenQuotes)
- `footer_quote`
- `footer_source`
- `quote_api_url` (default: `https://zenquotes.io/api/today`)
- `quote_cache_file` (default: `/tmp/epaper_daily_quote.json`)

Default: frase del giorno da ZenQuotes con cache locale giornaliera.

Optional weekday label overrides:

- `weekdays_full` (7 entries for header date)
- `weekdays_abbr` (7 entries for forecast labels)
- `months_full` (12 entries for header date)
- `months_abbr` (12 entries for header date)
- `header_weekday_format` (`full` or `abbr`)
- `header_month_format` (`full` or `abbr`)
- `forecast_weekday_format` (`full` or `abbr`)
- `clock_partial_refresh` (`true` enables partial updates in `clock-daemon`)
- `clock_daemon_interval_sec` (default `60`)
- `clock_daemon_full_every` (force full refresh every N ticks, default `5`)

## 5. Test

```bash
# PNG preview with demo data (no HA, no e-paper)
python3 ha_epaper_dashboard.py --simulate --demo --output preview.png

# PNG preview with live HA data (no e-paper)
python3 ha_epaper_dashboard.py --simulate --output preview.png

# Run on actual display
python3 ha_epaper_dashboard.py

# Run on display with explicit Waveshare path
python3 ha_epaper_dashboard.py --epd-lib-path ~/src/e-Paper/RaspberryPi_JetsonNano/python/lib

# Clock-only update (header only, reuses cached full image)
python3 ha_epaper_dashboard.py --mode clock --epd-lib-path ~/src/e-Paper/RaspberryPi_JetsonNano/python/lib

# Continuous clock daemon (recommended for real partial updates)
python3 ha_epaper_dashboard.py --mode clock-daemon --epd-lib-path ~/src/e-Paper/RaspberryPi_JetsonNano/python/lib

# Optional: override daemon timing
python3 ha_epaper_dashboard.py --mode clock-daemon --clock-interval-sec 60 --clock-full-every 5 --epd-lib-path ~/src/e-Paper/RaspberryPi_JetsonNano/python/lib
```

## 5b. Optional icon assets

You can use PNG icon files instead of built-in drawn icons.  
See `assets/icons/README.md` for full naming and directory layout.

Supported paths:

- `assets/icons/weather/<condition>.png`
- `assets/icons/rooms/<room_icon>.png`
- `assets/icons/weather_<condition>.png`
- `assets/icons/rooms_<room_icon>.png`

Name matching also supports `-`/`_` variants automatically.

```bash
# Use default assets/icons
python3 ha_epaper_dashboard.py --simulate --output preview.png

# Or provide a custom icons directory
python3 ha_epaper_dashboard.py --simulate --icons-dir /path/to/icons --output preview.png
```

## 6. Systemd

Recommended:

- one long-running daemon service
- every minute updates clock
- every N ticks (default 5) fetches HA + full refresh

Prebuilt unit files are provided in `systemd/` for user `dash` and path `/home/dash/src`.

Then enable:

```bash
sudo install -m 644 systemd/epaper-dashboard.service /etc/systemd/system/epaper-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now epaper-dashboard.service
```

## 7. Useful commands

```bash
systemctl status epaper-dashboard.service   # daemon status
journalctl -u epaper-dashboard.service -f   # live logs
sudo systemctl restart epaper-dashboard.service
```

## Status dot legend

- `○` empty = Comfort (18–24°C, humidity < 65%)
- `◉` ring = Temperature out of range
- `●` filled = High humidity (> 65%)
