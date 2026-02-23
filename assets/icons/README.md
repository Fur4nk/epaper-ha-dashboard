## Icon Assets

You can provide PNG icons instead of drawing icons in code.

Default lookup directory:

- `assets/icons`

You can override it with:

- CLI: `--icons-dir /path/to/icons`
- env: `EPD_ICONS_DIR=/path/to/icons`

Supported layouts:

- `assets/icons/weather/<condition>.png`
- `assets/icons/rooms/<room_icon>.png`
- `assets/icons/weather_<condition>.png`
- `assets/icons/rooms_<room_icon>.png`

Room icon names (from `config.json` `rooms[].icon`):

- `kitchen`
- `livingroom`
- `bedroom`
- `childroom`
- `bathroom`
- `laundry`
- `storage`

Weather icon names (recommended, Home Assistant conditions):

- `sunny`
- `clear-night`
- `partlycloudy`
- `cloudy`
- `rainy`
- `pouring`
- `snowy`
- `snowy-rainy`
- `fog`
- `hail`
- `lightning`
- `lightning-rainy`
- `windy`
- `windy-variant`
- `exceptional`

Normalization behavior:

- The loader tries the exact name, then `_`/`-` variants, then compact form.
- Example: `clear-night` also matches `clear_night.png` and `clearnight.png`.
- Example: `partlycloudy` also matches `partly_cloudy.png` and `partly-cloudy.png`.

Examples:

- `assets/icons/weather/partlycloudy.png`
- `assets/icons/weather/clear-night.png`
- `assets/icons/weather/lightning-rainy.png`
- `assets/icons/rooms/kitchen.png`
- `assets/icons/rooms/livingroom.png`

Notes:

- PNGs are converted to monochrome at render time.
- If an icon is missing, the script falls back to the built-in vector icon.
