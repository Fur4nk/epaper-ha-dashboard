from datetime import datetime

from PIL import Image, ImageDraw, ImageFont


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    out = (text or "").strip()
    while out and draw.textlength(out, font=font) > max_w:
        out = out[:-1].rstrip()
    if out != (text or "").strip():
        out = out[:-1].rstrip() + "…"
    return out


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int, max_lines: int):
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for w in words[1:]:
        trial = f"{current} {w}"
        if draw.textlength(trial, font=font) <= max_w:
            current = trial
        else:
            lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines:
        lines[-1] = _fit_text(draw, lines[-1], font, max_w)
    return lines


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict,
    now: datetime,
    *,
    width: int,
    header_h: int,
    show_clock: bool,
    header_title: str,
    weekdays_full: list,
    weekdays_abbr: list,
    months_full: list,
    months_abbr: list,
    header_weekday_format: str,
    header_month_format: str,
):
    draw.rectangle([(0, 0), (width, header_h)], fill=255)
    title_text = header_title.upper()
    draw.text((16, 8), title_text, fill=0, font=fonts["title"])
    weekday_labels = weekdays_full if header_weekday_format == "full" else weekdays_abbr
    month_labels = months_full if header_month_format == "full" else months_abbr
    day_name = weekday_labels[now.weekday()]
    month_name = month_labels[now.month - 1]
    date_text = f"{day_name} {now.day} {month_name} {now.year}"
    if show_clock:
        draw.text((width - 16, 8), now.strftime("%H:%M"), fill=0, font=fonts["time"], anchor="ra")
        draw.text((16, 36), date_text, fill=0, font=fonts["date"])
    else:
        title_w = int(draw.textlength(title_text, font=fonts["title"]))
        date_max_w = max(80, width - 16 - (16 + title_w + 24))
        date_upper = _fit_text(draw, date_text.upper(), fonts["date_large"], date_max_w)
        title_h = _text_size(draw, title_text, fonts["title"])[1]
        date_h = _text_size(draw, date_upper, fonts["date_large"])[1]
        date_y = 12 + max(0, title_h - date_h)
        draw.text((width - 16, date_y), date_upper, fill=0, font=fonts["date_large"], anchor="ra")
    draw.rectangle([(0, header_h - 3), (width, header_h - 1)], fill=0)


def update_clock_header(
    img: Image.Image,
    now: datetime,
    *,
    width: int,
    header_h: int,
    fonts: dict,
    show_clock: bool,
    header_title: str,
    weekdays_full: list,
    weekdays_abbr: list,
    months_full: list,
    months_abbr: list,
    header_weekday_format: str,
    header_month_format: str,
):
    draw = ImageDraw.Draw(img)
    draw_header(
        draw,
        fonts,
        now,
        width=width,
        header_h=header_h,
        show_clock=show_clock,
        header_title=header_title,
        weekdays_full=weekdays_full,
        weekdays_abbr=weekdays_abbr,
        months_full=months_full,
        months_abbr=months_abbr,
        header_weekday_format=header_weekday_format,
        header_month_format=header_month_format,
    )


def draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict,
    now: datetime,
    *,
    width: int,
    height: int,
    labels: dict,
    footer_text_fn,
    last_updated: datetime = None,
    footer_debug_text: str = "",
):
    footer_top = height - 76
    if last_updated is not None:
        stamp = f"{labels.get('last_updated', 'Last updated')} {last_updated.strftime('%H:%M')}"
        draw.text((width - 16, footer_top - 14), stamp, fill=0, font=fonts["tiny"], anchor="ra")
    draw.line([(16, footer_top), (width - 16, footer_top)], fill=0, width=1)
    quote_raw, source_raw = footer_text_fn(now)
    quote_font = fonts["weather_sub"]
    source_font = fonts["tiny"]
    max_w = width - 32
    quote_lines = _wrap_text(draw, quote_raw, quote_font, max_w, max_lines=3)
    source = _fit_text(draw, source_raw, source_font, max_w)

    source_h = _text_size(draw, source, source_font)[1] if source else 0
    y = footer_top + 6
    source_y = height - source_h - 4 if source else None

    for ln in quote_lines:
        if not ln:
            continue
        w, h = _text_size(draw, ln, quote_font)
        draw.text(((width - w) // 2, y), ln, fill=0, font=quote_font)
        y += h + 2
    if source:
        w, _ = _text_size(draw, source, source_font)
        draw.text(((width - w) // 2, source_y), source, fill=0, font=source_font)
    if footer_debug_text:
        draw.text((width - 3, height - 1), footer_debug_text, fill=0, font=fonts["tiny"], anchor="rd")


def render_dashboard(
    data: dict,
    now: datetime,
    *,
    width: int,
    height: int,
    header_h: int,
    fonts: dict,
    icon_assets,
    icons_cls,
    condition_labels: dict,
    intraday_labels: list,
    labels: dict,
    weekdays_full: list,
    weekdays_abbr: list,
    months_full: list,
    months_abbr: list,
    header_weekday_format: str,
    header_month_format: str,
    forecast_weekday_format: str,
    show_clock: bool,
    header_title: str,
    footer_text_fn,
    last_updated: datetime = None,
    footer_debug_text: str = "",
) -> Image.Image:
    img = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(img)
    draw_header(
        draw,
        fonts,
        now,
        width=width,
        header_h=header_h,
        show_clock=show_clock,
        header_title=header_title,
        weekdays_full=weekdays_full,
        weekdays_abbr=weekdays_abbr,
        months_full=months_full,
        months_abbr=months_abbr,
        header_weekday_format=header_weekday_format,
        header_month_format=header_month_format,
    )
    y = header_h

    y += 6
    weather = data["weather"]
    cond = weather.get("condition", "unknown")
    out_temp = weather.get("temperature")
    out_hum = weather.get("humidity")
    wind = weather.get("wind_speed")
    uv = weather.get("uv_index")
    dayparts = weather.get("dayparts", {}) if isinstance(weather, dict) else {}

    draw.text((16, y), labels.get("outdoor", "OUTDOOR"), fill=0, font=fonts["section"])
    y += 12

    row_y = y
    row_h = 82
    cond_text = condition_labels.get(cond, cond.replace("_", " ").title())

    left_x = 16
    split_x = 198
    if out_temp is not None:
        temp_num = f"{int(round(float(out_temp)))}"
        num_w = int(draw.textlength(temp_num, font=fonts["temp_outdoor"]))
        draw.text((left_x, row_y + 20), temp_num, fill=0, font=fonts["temp_outdoor"])
        draw.text((left_x + num_w - 2, row_y + 20), "°", fill=0, font=fonts["temp_outdoor"])
    else:
        draw.text((left_x, row_y + 20), "—°", fill=0, font=fonts["temp_outdoor"])
    info_x = left_x + 76
    cond_text = _fit_text(draw, cond_text, fonts["info"], split_x - info_x - 12)
    draw.text((info_x, row_y + 13), cond_text, fill=0, font=fonts["info"])
    label_w = 24
    draw.text((info_x, row_y + 27), labels.get("humidity_short", "Hu"), fill=0, font=fonts["info"])
    draw.text((info_x + label_w, row_y + 27),
              f"{out_hum:.0f}%" if out_hum is not None else "--%", fill=0, font=fonts["info"])
    wind_x = info_x + 2
    draw.text((wind_x, row_y + 40), labels.get("wind_short", "Wi"), fill=0, font=fonts["info"])
    draw.text((wind_x + label_w, row_y + 40),
              f"{wind:.0f} km/h" if wind is not None else "-- km/h", fill=0, font=fonts["info"])

    if uv is not None:
        uv_value = float(uv)
        if uv_value < 3:
            uv_level = "(low)"
        elif uv_value < 6:
            uv_level = "(medium)"
        else:
            uv_level = "(high)"
        uv_line = f"UV {uv_value:.1f} {uv_level}"
        uv_line = _fit_text(draw, uv_line, fonts["info"], split_x - info_x - 10)
        draw.text((info_x, row_y + 53), uv_line, fill=0, font=fonts["info"])

    sep_x = split_x - 8
    sep_y0 = row_y + 8
    sep_y1 = row_y + row_h - 8
    draw.line([(sep_x, sep_y0), (sep_x, sep_y1)], fill=0, width=1)

    intraday_keys = list(zip(intraday_labels, ["morning", "afternoon", "evening"]))
    col_w = (width - split_x - 8) // 3
    for i, (label, key) in enumerate(intraday_keys):
        fx = split_x + i * col_w + col_w // 2
        entry = dayparts.get(key, {}) if isinstance(dayparts, dict) else {}
        t_min = entry.get("min") if isinstance(entry, dict) else None
        t_max = entry.get("max") if isinstance(entry, dict) else None
        e_cond = entry.get("condition", cond) if isinstance(entry, dict) else cond
        mm_txt = f"{float(t_min):.0f}°/{float(t_max):.0f}°" if t_min is not None and t_max is not None else "—°/—°"
        draw.text((fx, row_y + 2), label, fill=0, font=fonts["fc_day"], anchor="mt")
        intraday_icon_ok = icon_assets.draw_weather(img, e_cond, fx, row_y + 40, 40) if icon_assets else False
        if not intraday_icon_ok:
            icons_cls.weather(draw, fx, row_y + 40, e_cond, r=20)
        draw.text((fx, row_y + 63), mm_txt, fill=0, font=fonts["fc_temp"], anchor="mt")

    y += row_h

    forecast = weather.get("forecast", [])
    if forecast:
        y += 2
        x0, x1 = 8, width - 8
        draw.line([(x0, y), (x1, y)], fill=0, width=1)
        y += 10
        n_fc = min(len(forecast), 4)
        fc_w = (x1 - x0) // n_fc
        for i, fc in enumerate(forecast[:n_fc]):
            fx = x0 + i * fc_w + fc_w // 2
            try:
                dt_str = fc["datetime"]
                fc_date = datetime.fromisoformat(dt_str.replace("Z", "+00:00")) if "T" in dt_str \
                    else datetime.strptime(dt_str[:10], "%Y-%m-%d")
                forecast_weekdays = weekdays_full if forecast_weekday_format == "full" else weekdays_abbr
                dl = forecast_weekdays[fc_date.weekday()]
            except Exception:
                dl = f"+{i+1}"
            draw.text((fx, y), dl, fill=0, font=fonts["fc_day"], anchor="mt")
            fc_cond = fc.get("condition", "unknown")
            fc_icon_ok = icon_assets.draw_weather(img, fc_cond, fx, y + 38, 46) if icon_assets else False
            if not fc_icon_ok:
                icons_cls.weather(draw, fx, y + 38, fc_cond, r=23)
            t_hi_v = fc.get("temperature")
            t_lo_v = fc.get("templow")
            t_hi = f"{int(round(float(t_hi_v)))}" if t_hi_v not in (None, "—") else "—"
            t_lo = f"{int(round(float(t_lo_v)))}" if t_lo_v not in (None, "—") else "—"
            draw.text((fx, y + 64), f"{t_hi}°/{t_lo}°", fill=0, font=fonts["fc_temp"], anchor="mt")
        y += 74

    y += 10
    draw.rectangle([(0, y), (width, y + 2)], fill=0)
    y += 10

    header_font = fonts["section"]
    draw.text((16, y - 4), labels.get("rooms", "ROOMS"), fill=0, font=header_font)
    col_t = width - 130
    col_h = width - 48
    draw.text((col_t + 20, y), labels.get("temp", "TEMP"), fill=0, font=header_font, anchor="mt")
    draw.text((col_h, y), labels.get("hum", "HUM"), fill=0, font=header_font, anchor="mt")
    y += 16
    draw.line([(16, y), (width - 16, y)], fill=0, width=1)
    y += 4

    rooms = data["rooms"]
    if not rooms:
        draw.text((16, y + 12), labels.get("no_rooms", "No rooms configured"), fill=0, font=fonts["tiny"])
        draw_footer(
            draw,
            fonts,
            now,
            width=width,
            height=height,
            labels=labels,
            footer_text_fn=footer_text_fn,
            last_updated=last_updated,
            footer_debug_text=footer_debug_text,
        )
        return img

    available = height - y - 30
    row_h = max(1, min(available // len(rooms), 54))

    for i, room in enumerate(rooms):
        ry = y + i * row_h
        ry_mid = ry + row_h // 2

        if i % 2 == 0:
            draw.rectangle([(0, ry), (width, ry + row_h - 1)], fill=248)

        room_icon_ok = icon_assets.draw_room(img, room["icon"], 30, ry_mid, 24) if icon_assets else False
        if not room_icon_ok:
            icons_cls.room(draw, 30, ry_mid, room["icon"], s=11)
        draw.text((54, ry_mid), room["name"], fill=0, font=fonts["room_name"], anchor="lm")

        if room["temp"] is not None:
            draw.text((col_t + 20, ry_mid), f"{room['temp']:.1f}°", fill=0,
                      font=fonts["temp_room"], anchor="mm")
        else:
            draw.text((col_t + 20, ry_mid), "—.—°", fill=0, font=fonts["temp_room"], anchor="mm")

        if room["hum"] is not None:
            draw.text((col_h, ry_mid), f"{room['hum']:.0f}%", fill=0,
                      font=fonts["hum_room"], anchor="mm")
        else:
            draw.text((col_h, ry_mid), "—%", fill=0, font=fonts["hum_room"], anchor="mm")

        sx = width - 14
        t, h = room["temp"], room["hum"]
        if t is not None and h is not None:
            if h > 65:
                draw.ellipse([sx - 5, ry_mid - 5, sx + 5, ry_mid + 5], fill=0)
            elif t > 24 or t < 18:
                draw.ellipse([sx - 5, ry_mid - 5, sx + 5, ry_mid + 5], outline=0, width=2)
                draw.ellipse([sx - 2, ry_mid - 2, sx + 2, ry_mid + 2], fill=0)
            else:
                draw.ellipse([sx - 5, ry_mid - 5, sx + 5, ry_mid + 5], outline=0, width=1)

        draw.line([(16, ry + row_h - 1), (width - 16, ry + row_h - 1)], fill=200, width=1)

    draw_footer(
        draw,
        fonts,
        now,
        width=width,
        height=height,
        labels=labels,
        footer_text_fn=footer_text_fn,
        last_updated=last_updated,
        footer_debug_text=footer_debug_text,
    )
    return img
