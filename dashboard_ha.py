import json
from datetime import datetime

import requests


def _ha_headers(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _fmt_next_sun_time(dt_str: str):
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M")
    except Exception:
        return None


def _get_state(ha_url: str, ha_token: str, entity_id: str, log):
    if not entity_id:
        return None
    try:
        r = requests.get(f"{ha_url}/api/states/{entity_id}", headers=_ha_headers(ha_token), timeout=10)
        r.raise_for_status()
        state = r.json().get("state")
        return None if state in ("unavailable", "unknown", None) else state
    except Exception as e:
        log.warning(f"Failed to fetch {entity_id}: {e}")
        return None


def _extract_dayparts_from_hourly(hourly_forecast: list):
    if not isinstance(hourly_forecast, list):
        return {}
    targets = {"morning": 9, "afternoon": 15, "evening": 21}
    phase_hours = {
        "morning": range(6, 12),
        "afternoon": range(12, 18),
        "evening": range(18, 24),
    }
    buckets = {k: [] for k in targets}
    today = datetime.now().date()
    for item in hourly_forecast:
        if not isinstance(item, dict):
            continue
        dt_str = item.get("datetime")
        temp = item.get("temperature")
        cond = item.get("condition", "unknown")
        if dt_str is None or temp is None:
            continue
        try:
            dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.date() != today:
            continue
        for key, hours in phase_hours.items():
            if dt.hour in hours:
                buckets[key].append({"temp": float(temp), "cond": cond, "hour": dt.hour})
                break

    result = {}
    for key, samples in buckets.items():
        if not samples:
            continue
        t_min = min(s["temp"] for s in samples)
        t_max = max(s["temp"] for s in samples)
        target_h = targets[key]
        rep = min(samples, key=lambda s: abs(s["hour"] - target_h))
        result[key] = {"min": t_min, "max": t_max, "condition": rep["cond"]}
    return result


def _normalize_daypart_entry(entry):
    if not isinstance(entry, dict):
        return None
    t_min = _to_float(entry.get("min"))
    t_max = _to_float(entry.get("max"))
    cond = str(entry.get("condition", "unknown"))
    if t_min is None or t_max is None:
        return None
    return {"min": t_min, "max": t_max, "condition": cond}


def _read_dayparts_cache(cache_file: str, weather_entity: str, today_key: str):
    try:
        with open(cache_file) as f:
            payload = json.load(f)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("date") != today_key:
        return {}
    if payload.get("entity_id") != weather_entity:
        return {}
    raw_dayparts = payload.get("dayparts", {})
    if not isinstance(raw_dayparts, dict):
        return {}
    out = {}
    for key, value in raw_dayparts.items():
        normalized = _normalize_daypart_entry(value)
        if normalized:
            out[key] = normalized
    return out


def _write_dayparts_cache(cache_file: str, weather_entity: str, today_key: str, dayparts: dict, log):
    if not isinstance(dayparts, dict):
        return
    safe_dayparts = {}
    for key, value in dayparts.items():
        normalized = _normalize_daypart_entry(value)
        if normalized:
            safe_dayparts[key] = normalized
    payload = {"date": today_key, "entity_id": weather_entity, "dayparts": safe_dayparts}
    try:
        with open(cache_file, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        log.warning(f"Failed to write dayparts cache {cache_file}: {e}")


def _merge_daypart_minmax(cached_entry, new_entry):
    cached = _normalize_daypart_entry(cached_entry)
    fresh = _normalize_daypart_entry(new_entry)
    if cached and fresh:
        return {
            "min": min(cached["min"], fresh["min"]),
            "max": max(cached["max"], fresh["max"]),
            "condition": fresh.get("condition") or cached.get("condition") or "unknown",
        }
    return fresh or cached


def _get_weather(
    ha_url: str,
    ha_token: str,
    weather_entity: str,
    outdoor_temp: str,
    outdoor_hum: str,
    outdoor_uv: str,
    outdoor_aqi: str,
    outdoor_pm25: str,
    sun_entity: str,
    dayparts_cache_file: str,
    log,
) -> dict:
    result = {"condition": "unknown", "temperature": None, "humidity": None,
              "wind_speed": None, "uv_index": None, "aqi": None, "pm25": None,
              "sunrise_time": None, "sunset_time": None,
              "forecast": [], "dayparts": {}}
    if weather_entity:
        try:
            r = requests.post(f"{ha_url}/api/services/weather/get_forecasts?return_response",
                              headers=_ha_headers(ha_token),
                              json={"entity_id": weather_entity, "type": "daily"}, timeout=10)
            if r.ok:
                svc = r.json()
                if isinstance(svc, dict):
                    service_response = svc.get("service_response")
                    if isinstance(service_response, dict):
                        weather_data = service_response.get(weather_entity)
                        if isinstance(weather_data, dict) and "forecast" in weather_data:
                            result["forecast"] = weather_data["forecast"][:4]
                    if not result["forecast"]:
                        for val in svc.values():
                            if isinstance(val, dict) and "forecast" in val:
                                result["forecast"] = val["forecast"][:4]
                                break
                            if isinstance(val, dict):
                                for inner in val.values():
                                    if isinstance(inner, dict) and "forecast" in inner:
                                        result["forecast"] = inner["forecast"][:4]
                                        break
                                if result["forecast"]:
                                    break
        except Exception:
            pass
        try:
            r = requests.post(f"{ha_url}/api/services/weather/get_forecasts?return_response",
                              headers=_ha_headers(ha_token),
                              json={"entity_id": weather_entity, "type": "hourly"}, timeout=10)
            if r.ok:
                svc = r.json()
                service_response = svc.get("service_response", {}) if isinstance(svc, dict) else {}
                weather_data = service_response.get(weather_entity, {}) if isinstance(service_response, dict) else {}
                hourly = weather_data.get("forecast", []) if isinstance(weather_data, dict) else []
                result["dayparts"] = _extract_dayparts_from_hourly(hourly)
        except Exception:
            pass

        today_key = datetime.now().strftime("%Y-%m-%d")
        cached_dayparts = _read_dayparts_cache(dayparts_cache_file, weather_entity, today_key)
        merged_dayparts = dict(result["dayparts"]) if isinstance(result["dayparts"], dict) else {}
        for key in ("morning", "afternoon"):
            merged_entry = _merge_daypart_minmax(cached_dayparts.get(key), merged_dayparts.get(key))
            if merged_entry:
                merged_dayparts[key] = merged_entry
        if merged_dayparts:
            _write_dayparts_cache(dayparts_cache_file, weather_entity, today_key, merged_dayparts, log)
            result["dayparts"] = merged_dayparts

        try:
            r = requests.get(f"{ha_url}/api/states/{weather_entity}", headers=_ha_headers(ha_token), timeout=10)
            r.raise_for_status()
            data = r.json()
            result["condition"] = data.get("state", "unknown")
            attrs = data.get("attributes", {})
            result["temperature"] = attrs.get("temperature")
            result["humidity"] = attrs.get("humidity")
            result["wind_speed"] = attrs.get("wind_speed")
            result["uv_index"] = attrs.get("uv_index")
            result["aqi"] = attrs.get("aqi")
            result["pm25"] = attrs.get("pm25")
            if not result["forecast"]:
                result["forecast"] = attrs.get("forecast", [])[:4]
        except Exception as e:
            log.warning(f"Failed to fetch weather: {e}")
    else:
        log.warning("weather_entity is empty in config.json")

    out_t = _get_state(ha_url, ha_token, outdoor_temp, log)
    out_h = _get_state(ha_url, ha_token, outdoor_hum, log)
    out_uv = _get_state(ha_url, ha_token, outdoor_uv, log)
    out_aqi = _get_state(ha_url, ha_token, outdoor_aqi, log)
    out_pm25 = _get_state(ha_url, ha_token, outdoor_pm25, log)
    if out_t is not None:
        result["temperature"] = float(out_t)
    if out_h is not None:
        result["humidity"] = float(out_h)
    if out_uv is not None:
        result["uv_index"] = _to_float(out_uv)
    if out_aqi is not None:
        result["aqi"] = _to_float(out_aqi)
    if out_pm25 is not None:
        result["pm25"] = _to_float(out_pm25)

    try:
        r = requests.get(f"{ha_url}/api/states/{sun_entity}", headers=_ha_headers(ha_token), timeout=10)
        r.raise_for_status()
        sun = r.json()
        attrs = sun.get("attributes", {})
        result["sunrise_time"] = _fmt_next_sun_time(attrs.get("next_rising"))
        result["sunset_time"] = _fmt_next_sun_time(attrs.get("next_setting"))
    except Exception:
        pass
    return result


def fetch_all_data(
    ha_url: str,
    ha_token: str,
    rooms: list,
    weather_entity: str,
    outdoor_temp: str,
    outdoor_hum: str,
    outdoor_uv: str,
    outdoor_aqi: str,
    outdoor_pm25: str,
    sun_entity: str,
    dayparts_cache_file: str,
    log,
) -> dict:
    out_rooms = []
    for room in rooms:
        t = _get_state(ha_url, ha_token, room["temp"], log)
        h = _get_state(ha_url, ha_token, room["hum"], log)
        out_rooms.append(
            {
                "name": room["name"],
                "icon": room["icon"],
                "temp": float(t) if t else None,
                "hum": float(h) if h else None,
            }
        )
    return {
        "rooms": out_rooms,
        "weather": _get_weather(
            ha_url,
            ha_token,
            weather_entity,
            outdoor_temp,
            outdoor_hum,
            outdoor_uv,
            outdoor_aqi,
            outdoor_pm25,
            sun_entity,
            dayparts_cache_file,
            log,
        ),
    }
