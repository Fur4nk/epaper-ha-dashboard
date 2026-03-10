# Usage

## Main commands

PNG preview (live HA data, no e-Paper write):

```bash
python3 ha_epaper_dashboard.py --simulate --output preview.png
```

PNG preview with demo data:

```bash
python3 ha_epaper_dashboard.py --simulate --demo --output preview.png
```

Full render to panel:

```bash
python3 ha_epaper_dashboard.py --mode full --epd-lib-path ~/src/e-Paper/RaspberryPi_JetsonNano/python/lib
```

Clock daemon mode (recommended):

```bash
python3 ha_epaper_dashboard.py --mode clock-daemon --epd-lib-path ~/src/e-Paper/RaspberryPi_JetsonNano/python/lib
```

## Modes

- `full`: fetch data, render full frame, push full refresh.
- `clock`: one-shot update using cached full image plus header update.
- `clock-daemon`: long-running loop with configurable data/clock/full cadence.

## CLI options

- `--simulate`: output PNG instead of driving panel.
- `--demo`: use built-in fake data.
- `--output <path>`: PNG output path in simulate mode.
- `--mode {full,clock,clock-daemon}`
- `--epd-lib-path <path>`: Waveshare python lib directory.
- `--icons-dir <path>`: custom icons root.
- `--clock-partial-refresh`: force partial refresh use in clock modes.
- `--cache-image <path>`: full image cache (default `/tmp/epaper_dashboard_full.png`).
- `--clock-interval-sec <int>`
- `--clock-data-every-min <int>`
- `--clock-full-every <int>` (display ticks, not minutes; alias: `--clock-full-every-ticks`)

## Refresh behavior summary

In `clock-daemon`:

- Every tick (`clock_daemon_interval_sec`): evaluate what to update.
- Every `clock_daemon_data_every_min`: fetch HA data and redraw dynamic regions.
- Every `clock_daemon_full_every_ticks` display ticks: force full refresh to limit artifacts.
- If `show_clock` is `false`, clock-only redraws are skipped.
- If `clock_partial_fullscreen` is `false`, data ticks avoid partial updates and refresh the panel only when non-clock data changed.

## Icons

For PNG icon asset naming and folder layout, see `assets/icons/README.md`.
