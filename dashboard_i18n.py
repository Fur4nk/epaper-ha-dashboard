import json
import os


DEFAULT_I18N = {
    "weekdays_abbr": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "weekdays_full": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "months_abbr": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "months_full": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
    "intraday_labels": ["Morning", "Afternoon", "Evening"],
    "condition_labels": {
        "sunny": "Sunny", "clear-night": "Clear", "partlycloudy": "Partly cloudy",
        "cloudy": "Cloudy", "rainy": "Rain", "pouring": "Heavy rain",
        "snowy": "Snow", "snowy-rainy": "Sleet", "fog": "Fog",
        "hail": "Hail", "lightning": "Storm", "lightning-rainy": "Storm",
        "windy": "Windy", "windy-variant": "Windy", "exceptional": "Exceptional",
    },
    "labels": {
        "last_updated": "Last updated",
        "outdoor": "OUTDOOR",
        "rooms": "ROOMS",
        "temp": "TEMP",
        "hum": "HUM",
        "humidity_short": "Hu",
        "wind_short": "Wi",
    },
    "fallback_quote": {
        "text": "It always seems impossible until it is done.",
        "author": "Nelson Mandela",
    },
}


def load_i18n_bundle(locale: str, i18n_dir: str, log):
    bundle = dict(DEFAULT_I18N)
    locale_path = os.path.join(i18n_dir, f"{locale}.json")
    try:
        with open(locale_path) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if isinstance(value, dict) and isinstance(bundle.get(key), dict):
                    merged = dict(bundle[key])
                    merged.update(value)
                    bundle[key] = merged
                else:
                    bundle[key] = value
    except Exception as e:
        log.warning(f"Failed to load locale '{locale}' from {locale_path}: {e}. Using defaults.")

    weekdays_abbr = bundle.get("weekdays_abbr", DEFAULT_I18N["weekdays_abbr"])
    weekdays_full = bundle.get("weekdays_full", DEFAULT_I18N["weekdays_full"])
    months_abbr = bundle.get("months_abbr", DEFAULT_I18N["months_abbr"])
    months_full = bundle.get("months_full", DEFAULT_I18N["months_full"])
    intraday_labels = bundle.get("intraday_labels", DEFAULT_I18N["intraday_labels"])
    condition_labels = bundle.get("condition_labels", DEFAULT_I18N["condition_labels"])
    labels = bundle.get("labels", DEFAULT_I18N["labels"])
    fallback_quote = bundle.get("fallback_quote", DEFAULT_I18N["fallback_quote"])

    if not isinstance(weekdays_abbr, list) or len(weekdays_abbr) != 7:
        log.warning("Invalid i18n weekdays_abbr, using defaults")
        weekdays_abbr = DEFAULT_I18N["weekdays_abbr"]
    if not isinstance(weekdays_full, list) or len(weekdays_full) != 7:
        log.warning("Invalid i18n weekdays_full, using defaults")
        weekdays_full = DEFAULT_I18N["weekdays_full"]
    if not isinstance(months_abbr, list) or len(months_abbr) != 12:
        log.warning("Invalid i18n months_abbr, using defaults")
        months_abbr = DEFAULT_I18N["months_abbr"]
    if not isinstance(months_full, list) or len(months_full) != 12:
        log.warning("Invalid i18n months_full, using defaults")
        months_full = DEFAULT_I18N["months_full"]
    if not isinstance(intraday_labels, list) or len(intraday_labels) != 3:
        log.warning("Invalid i18n intraday_labels, using defaults")
        intraday_labels = DEFAULT_I18N["intraday_labels"]
    if not isinstance(condition_labels, dict):
        log.warning("Invalid i18n condition_labels, using defaults")
        condition_labels = DEFAULT_I18N["condition_labels"]
    if not isinstance(labels, dict):
        log.warning("Invalid i18n labels, using defaults")
        labels = DEFAULT_I18N["labels"]
    if not isinstance(fallback_quote, dict):
        fallback_quote = DEFAULT_I18N["fallback_quote"]

    return {
        "weekdays_abbr": weekdays_abbr,
        "weekdays_full": weekdays_full,
        "months_abbr": months_abbr,
        "months_full": months_full,
        "intraday_labels": intraday_labels,
        "condition_labels": condition_labels,
        "labels": labels,
        "fallback_quote": fallback_quote,
    }
