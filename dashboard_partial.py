from dashboard_renderer import FORECAST_ROW_H, OUTDOOR_ROW_H


def _rounded_or_none(value, to_float, digits):
    parsed = to_float(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def _room_status_key(
    temp_v,
    hum_v,
    to_float,
    room_temp_min: float = 18.0,
    room_temp_max: float = 24.0,
    room_humidity_max: float = 65.0,
):
    t = to_float(temp_v)
    h = to_float(hum_v)
    if t is None or h is None:
        return "na"
    if h > room_humidity_max:
        return "high_hum"
    if t > room_temp_max or t < room_temp_min:
        return "temp_alert"
    return "ok"


def build_data_snapshot(
    data: dict,
    to_float,
    room_temp_min: float = 18.0,
    room_temp_max: float = 24.0,
    room_humidity_max: float = 65.0,
):
    weather = data.get("weather", {}) if isinstance(data, dict) else {}
    dayparts = weather.get("dayparts", {}) if isinstance(weather, dict) else {}
    forecast = weather.get("forecast", []) if isinstance(weather, dict) else []
    alerts = weather.get("alerts", []) if isinstance(weather, dict) else []
    alert = weather.get("alert", {}) if isinstance(weather, dict) else {}
    rooms = data.get("rooms", []) if isinstance(data, dict) else []

    outdoor = (
        _rounded_or_none(weather.get("temperature"), to_float, 1),
        _rounded_or_none(weather.get("humidity"), to_float, 0),
        _rounded_or_none(weather.get("wind_speed"), to_float, 0),
        _rounded_or_none(weather.get("uv_index"), to_float, 1),
        str(weather.get("condition", "unknown")),
    )

    normalized_alerts = alerts if isinstance(alerts, list) and alerts else ([alert] if isinstance(alert, dict) and alert else [])
    alert_key = tuple(
        (
            str(item.get("event", "")),
            str(item.get("severity", "")),
            str(item.get("onset", "")),
            str(item.get("expires", "")),
            str(item.get("level", "")),
            str(item.get("type", "")),
        )
        for item in normalized_alerts
        if isinstance(item, dict)
    ) or None

    intraday = []
    for key in ("morning", "afternoon", "evening"):
        entry = dayparts.get(key, {}) if isinstance(dayparts, dict) else {}
        intraday.append(
            (
                key,
                str(entry.get("condition", "unknown")),
                _rounded_or_none(entry.get("min"), to_float, 1),
                _rounded_or_none(entry.get("max"), to_float, 1),
            )
        )

    fc = []
    for item in forecast[:4]:
        if not isinstance(item, dict):
            continue
        fc.append(
            (
                str(item.get("datetime", "")),
                str(item.get("condition", "unknown")),
                _rounded_or_none(item.get("temperature"), to_float, 1),
                _rounded_or_none(item.get("templow"), to_float, 1),
            )
        )

    room_values = []
    for room in rooms:
        if not isinstance(room, dict):
            continue
        metrics = room.get("metrics", []) if isinstance(room.get("metrics"), list) else []
        metric_values = []
        for metric in metrics[:3]:
            if not isinstance(metric, dict):
                continue
            metric_values.append(
                (
                    str(metric.get("key", "")),
                    _rounded_or_none(metric.get("value"), to_float, int(metric.get("decimals", 0) or 0)),
                )
            )
        t = _rounded_or_none(room.get("temp"), to_float, 1)
        h = _rounded_or_none(room.get("hum"), to_float, 0)
        status = _room_status_key(
            room.get("temp"),
            room.get("hum"),
            to_float,
            room_temp_min=room_temp_min,
            room_temp_max=room_temp_max,
            room_humidity_max=room_humidity_max,
        )
        room_values.append((tuple(metric_values), t, h, status))

    return {
        "outdoor": outdoor,
        "intraday": tuple(intraday),
        "forecast": tuple(fc),
        "alert": alert_key,
        "rooms": tuple(room_values),
    }


def diff_snapshots(prev_snap, curr_snap):
    if prev_snap is None:
        return {"outdoor": True, "intraday": True, "forecast": True, "alert": True, "rooms": None, "footer": True}

    room_changes = set()
    prev_rooms = list(prev_snap.get("rooms", ()))
    curr_rooms = list(curr_snap.get("rooms", ()))
    max_rows = max(len(prev_rooms), len(curr_rooms))
    for idx in range(max_rows):
        if idx >= len(prev_rooms) or idx >= len(curr_rooms) or prev_rooms[idx] != curr_rooms[idx]:
            room_changes.add(idx)

    return {
        "outdoor": prev_snap.get("outdoor") != curr_snap.get("outdoor"),
        "intraday": prev_snap.get("intraday") != curr_snap.get("intraday"),
        "forecast": prev_snap.get("forecast") != curr_snap.get("forecast"),
        "alert": prev_snap.get("alert") != curr_snap.get("alert"),
        "rooms": room_changes,
        "footer": True,
    }


def build_dynamic_partial_rects(data: dict, header_h: int, width: int, height: int, changed: dict = None):
    rects = []
    y = header_h
    y += 6
    y += 12
    row_y = y
    row_h = OUTDOOR_ROW_H

    if changed is None or changed.get("outdoor") or changed.get("alert"):
        rects.append((12, row_y, 190, row_y + row_h))
    if changed is None or changed.get("intraday"):
        rects.append((190, row_y + 18, width, row_y + row_h))
    y += row_h

    weather = data.get("weather", {}) if isinstance(data, dict) else {}
    forecast = weather.get("forecast", []) if isinstance(weather, dict) else []
    if forecast:
        y += 4
        y += 10
        fc_top = y
        if changed is None or changed.get("forecast") or changed.get("alert"):
            rects.append((8, fc_top, width - 8, fc_top + FORECAST_ROW_H))
        y += FORECAST_ROW_H

    y += 10
    y += 10
    y += 16
    y += 4
    rooms_y = y
    rooms = data.get("rooms", []) if isinstance(data, dict) else []
    if rooms:
        available = height - rooms_y - 30
        row_h = min(available // len(rooms), 54)
        room_changes = None if changed is None else changed.get("rooms")
        if room_changes is None:
            rooms_bottom = rooms_y + len(rooms) * row_h
            rects.append((width - 180, rooms_y, width, rooms_bottom))
        else:
            for idx in sorted(room_changes):
                if idx < 0 or idx >= len(rooms):
                    continue
                y0 = rooms_y + idx * row_h
                y1 = y0 + row_h
                rects.append((width - 180, y0, width, y1))

    footer_top = height - 76
    if changed is None or changed.get("footer"):
        rects.append((0, footer_top - 18, width, height))

    return rects
