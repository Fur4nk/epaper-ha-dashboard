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


def _parse_local_datetime(dt_str: str):
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone()
    return dt


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
        dt = _parse_local_datetime(dt_str)
        if dt is None:
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


def _select_multiday_forecast(forecast: list, limit: int = 4):
    if not isinstance(forecast, list):
        return []
    tomorrow = datetime.now().date().toordinal() + 1
    selected = []
    for item in forecast:
        if not isinstance(item, dict):
            continue
        dt_str = item.get("datetime")
        if dt_str:
            fc_dt = _parse_local_datetime(dt_str)
            if fc_dt is not None and fc_dt.date().toordinal() < tomorrow:
                continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _parse_alert_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _severity_rank(*values):
    for value in values:
        token = str(value or "").strip().lower()
        if not token:
            continue
        if token in ("red", "extreme", "warning", "level4", "4"):
            return 4
        if token in ("orange", "severe", "major", "level3", "3"):
            return 3
        if token in ("yellow", "moderate", "level2", "2"):
            return 2
        if token in ("minor", "level1", "1"):
            return 1
    return 0


def _normalize_alert_item(item):
    if not isinstance(item, dict):
        return None
    event = str(item.get("event") or item.get("title") or item.get("name") or "").strip()
    headline = str(item.get("headline") or item.get("description") or "").strip()
    severity = str(item.get("severity") or item.get("awareness_level") or item.get("level") or "").strip()
    onset = item.get("onset") or item.get("effective") or item.get("start")
    expires = item.get("expires") or item.get("ends") or item.get("end")
    alert_type = str(item.get("awareness_type") or item.get("type") or "").strip()
    if not any((event, headline, severity, onset, expires, alert_type)):
        return None
    if not event:
        event = headline or "Weather Alert"
    return {
        "event": event,
        "severity": severity,
        "headline": headline,
        "onset": onset,
        "expires": expires,
        "level": str(item.get("awareness_level", "")).strip(),
        "type": alert_type,
        "severity_rank": _severity_rank(severity, item.get("awareness_level")),
    }


def _normalize_alerts_from_entity(state: str, attrs: dict):
    attrs = attrs if isinstance(attrs, dict) else {}
    alerts = []
    for key in ("alerts", "entries", "warnings", "features"):
        raw_items = attrs.get(key)
        if isinstance(raw_items, list):
            for item in raw_items:
                normalized = _normalize_alert_item(item)
                if normalized:
                    alerts.append(normalized)
    if not alerts and state not in ("off", "unavailable", "unknown", None):
        normalized = _normalize_alert_item(attrs)
        if normalized:
            alerts.append(normalized)

    deduped = []
    seen = set()
    for alert in alerts:
        key = (
            alert.get("event", ""),
            alert.get("severity", ""),
            alert.get("onset", ""),
            alert.get("expires", ""),
            alert.get("type", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alert)

    def _sort_key(alert):
        onset_dt = _parse_alert_datetime(alert.get("onset"))
        expires_dt = _parse_alert_datetime(alert.get("expires"))
        onset_key = onset_dt.timestamp() if onset_dt else float("inf")
        expires_key = expires_dt.timestamp() if expires_dt else float("inf")
        return (-int(alert.get("severity_rank", 0)), onset_key, expires_key, alert.get("event", ""))

    deduped.sort(key=_sort_key)
    return deduped


def _primary_alert(alerts):
    if isinstance(alerts, list) and alerts:
        return alerts[0]
    return None


def _room_metric_payload(metric: dict, value):
    metric = metric if isinstance(metric, dict) else {}
    numeric_value = _to_float(value)
    return {
        "key": str(metric.get("key", "")).strip().lower(),
        "label": str(metric.get("label", "")).strip(),
        "label_key": str(metric.get("label_key", metric.get("key", ""))).strip().lower(),
        "unit": str(metric.get("unit", "")).strip(),
        "decimals": int(metric.get("decimals", 0)) if str(metric.get("decimals", "")).strip() else 0,
        "value": numeric_value,
        "raw": value,
    }


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
    weather_alert_entity: str,
    dayparts_cache_file: str,
    log,
) -> dict:
    result = {"condition": "unknown", "temperature": None, "humidity": None,
              "wind_speed": None, "uv_index": None, "aqi": None, "pm25": None,
              "sunrise_time": None, "sunset_time": None,
              "forecast": [], "dayparts": {}, "alert": None, "alerts": []}
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
                            result["forecast"] = _select_multiday_forecast(weather_data["forecast"])
                    if not result["forecast"]:
                        for val in svc.values():
                            if isinstance(val, dict) and "forecast" in val:
                                result["forecast"] = _select_multiday_forecast(val["forecast"])
                                break
                            if isinstance(val, dict):
                                for inner in val.values():
                                    if isinstance(inner, dict) and "forecast" in inner:
                                        result["forecast"] = _select_multiday_forecast(inner["forecast"])
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
                result["forecast"] = _select_multiday_forecast(attrs.get("forecast", []))
        except Exception as e:
            log.warning(f"Failed to fetch weather: {e}")
    else:
        log.warning("weather_entity is empty in config.json")

    # Alert fetching
    if weather_alert_entity:
        try:
            r = requests.get(f"{ha_url}/api/states/{weather_alert_entity}", headers=_ha_headers(ha_token), timeout=10)
            if r.ok:
                data = r.json()
                state = data.get("state")
                log.info(f"Alert entity {weather_alert_entity} state: {state}")
                attrs = data.get("attributes", {})
                result["alerts"] = _normalize_alerts_from_entity(state, attrs)
                result["alert"] = _primary_alert(result["alerts"])
        except Exception as e:
            log.warning(f"Failed to fetch alerts: {e}")

    out_t = _get_state(ha_url, ha_token, outdoor_temp, log)
    out_h = _get_state(ha_url, ha_token, outdoor_hum, log)
    out_uv = _get_state(ha_url, ha_token, outdoor_uv, log)
    out_aqi = _get_state(ha_url, ha_token, outdoor_aqi, log)
    out_pm25 = _get_state(ha_url, ha_token, outdoor_pm25, log)
    if out_t is not None:
        result["temperature"] = _to_float(out_t)
    if out_h is not None:
        result["humidity"] = _to_float(out_h)
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
    weather_alert_entity: str,
    dayparts_cache_file: str,
    log,
) -> dict:
    out_rooms = []
    for room in rooms:
        metrics = []
        for metric in room.get("metrics", []) if isinstance(room, dict) else []:
            entity_id = str(metric.get("entity", "")).strip()
            metric_value = _get_state(ha_url, ha_token, entity_id, log)
            metrics.append(_room_metric_payload(metric, metric_value))
        t = _get_state(ha_url, ha_token, room["temp"], log)
        h = _get_state(ha_url, ha_token, room["hum"], log)
        if not room.get("temp"):
            for metric in metrics:
                if metric.get("key") == "temp":
                    t = metric.get("value")
                    break
        if not room.get("hum"):
            for metric in metrics:
                if metric.get("key") == "hum":
                    h = metric.get("value")
                    break
        out_rooms.append(
            {
                "name": room["name"],
                "icon": room["icon"],
                "temp": _to_float(t),
                "hum": _to_float(h),
                "metrics": metrics,
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
            weather_alert_entity,
            dayparts_cache_file,
            log,
        ),
    }
