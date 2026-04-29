#!/usr/bin/env python3
"""
Home Assistant e-Paper Dashboard — Waveshare 7.5" V2 (800×480)
Portrait mode (480×800): rooms + outdoor weather + forecast.

System dependencies only (no pip):
    sudo apt install python3-pil python3-numpy python3-rpi.gpio python3-spidev
    git clone https://github.com/waveshare/e-Paper

Usage:
    python3 ha_epaper_dashboard.py              # normal run
    python3 ha_epaper_dashboard.py --simulate   # save PNG preview, no hardware
"""

import os
import sys
import math
import time
import logging
import argparse
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont
from dashboard_ha import fetch_all_data as fetch_all_data_from_ha
from dashboard_epd import (
    first_callable,
    load_epd_driver,
    safe_partial_refresh,
    send_to_epaper as epd_send_to_epaper,
)
from dashboard_i18n import DEFAULT_I18N, load_i18n_bundle
from dashboard_partial import build_data_snapshot, build_dynamic_partial_rects, diff_snapshots
from dashboard_renderer import render_dashboard, update_clock_header as renderer_update_clock_header

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CONFIG — loaded from external files                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_json(filename: str, required: bool = True) -> dict:
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        if required:
            print(f"ERROR: {path} not found. Copy {filename}.example to {filename} and edit it.")
            sys.exit(1)
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        if required:
            print(f"ERROR: failed to parse {path}: {e}")
            sys.exit(1)
        return {}


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


I18N_DIR = os.path.join(SCRIPT_DIR, "i18n")

W, H = 480, 800
HEADER_H = 56

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
DEFAULT_ICON_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")


@dataclass
class DashboardSettings:
    ha_url: str = ""
    ha_token: str = ""
    rooms: list = field(default_factory=list)
    weather_entity: str = ""
    weather_alert_entity: str = ""
    outdoor_temp: str = ""
    outdoor_hum: str = ""
    outdoor_uv: str = ""
    outdoor_aqi: str = ""
    outdoor_pm25: str = ""
    sun_entity: str = "sun.sun"
    footer_daily_quote: bool = True
    footer_quote: str = ""
    footer_source: str = ""
    quote_api_url: str = "https://zenquotes.io/api/today"
    quote_cache_file: str = "/tmp/epaper_daily_quote.json"
    dayparts_cache_file: str = "/tmp/epaper_dayparts_cache.json"
    header_weekday_format: str = "full"
    header_month_format: str = "full"
    forecast_weekday_format: str = "abbr"
    locale: str = "en"
    header_title: str = "HOUSE"
    clock_partial_refresh: bool = True
    clock_partial_fullscreen: bool = True
    clock_daemon_interval_sec: int = 60
    clock_daemon_full_every: int = 240
    clock_daemon_data_every_min: int = 10
    show_clock: bool = True
    footer_debug_ticks: bool = False
    room_temp_min: float = 18.0
    room_temp_max: float = 24.0
    room_humidity_max: float = 65.0
    blocks: list = field(default_factory=lambda: ["outdoor", "forecast", "rooms", "footer"])
    weekdays_abbr: list = field(default_factory=lambda: list(DEFAULT_I18N["weekdays_abbr"]))
    weekdays_full: list = field(default_factory=lambda: list(DEFAULT_I18N["weekdays_full"]))
    months_abbr: list = field(default_factory=lambda: list(DEFAULT_I18N["months_abbr"]))
    months_full: list = field(default_factory=lambda: list(DEFAULT_I18N["months_full"]))
    intraday_labels: list = field(default_factory=lambda: list(DEFAULT_I18N["intraday_labels"]))
    condition_labels: dict = field(default_factory=lambda: dict(DEFAULT_I18N["condition_labels"]))
    labels: dict = field(default_factory=lambda: dict(DEFAULT_I18N["labels"]))
    fallback_quote: tuple = field(
        default_factory=lambda: (
            str(DEFAULT_I18N["fallback_quote"]["text"]),
            str(DEFAULT_I18N["fallback_quote"]["author"]),
        )
    )


def _normalize_room_metric(metric: dict):
    if not isinstance(metric, dict):
        return None
    key = str(metric.get("key", "")).strip().lower()
    entity = str(metric.get("entity", "")).strip()
    if not key or not entity:
        return None
    label = str(metric.get("label", "")).strip()
    label_key = str(metric.get("label_key", key)).strip().lower() or key
    decimals = max(0, _to_int(metric.get("decimals", 0), 0))
    unit = str(metric.get("unit", "")).strip()
    return {
        "key": key,
        "label": label,
        "label_key": label_key,
        "entity": entity,
        "decimals": decimals,
        "unit": unit,
    }


def _normalize_room(room: dict):
    if not isinstance(room, dict):
        return None
    name = str(room.get("name", "")).strip()
    if not name:
        return None
    icon = str(room.get("icon", "room")).strip() or "room"
    metrics = []
    raw_metrics = room.get("metrics", [])
    if isinstance(raw_metrics, list):
        for metric in raw_metrics:
            normalized = _normalize_room_metric(metric)
            if normalized:
                metrics.append(normalized)
    temp_entity = str(room.get("temp", "")).strip()
    hum_entity = str(room.get("hum", "")).strip()
    if not metrics:
        if temp_entity:
            metrics.append({"key": "temp", "label": "", "label_key": "temp", "entity": temp_entity, "decimals": 1, "unit": "°"})
        if hum_entity:
            metrics.append({"key": "hum", "label": "", "label_key": "hum", "entity": hum_entity, "decimals": 0, "unit": "%"})
    return {
        "name": name,
        "icon": icon,
        "temp": temp_entity,
        "hum": hum_entity,
        "metrics": metrics,
    }

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  LOGGING                                                                 ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("epaper")

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  FONTS                                                                   ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def load_fonts() -> dict:
    try:
        reg  = os.path.join(FONT_DIR, "DejaVuSans.ttf")
        bold = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
        mono = os.path.join(FONT_DIR, "DejaVuSansMono-Bold.ttf")
        return {
            "title":       ImageFont.truetype(bold, 32),
            "time":        ImageFont.truetype(mono, 32),
            "date":        ImageFont.truetype(reg, 16),
            "date_large":  ImageFont.truetype(bold, 18),
            "section":     ImageFont.truetype(bold, 15),
            "room_name":   ImageFont.truetype(bold, 21),
            "temp_outdoor": ImageFont.truetype(mono, 42),
            "temp_big":    ImageFont.truetype(mono, 34),
            "temp_room":   ImageFont.truetype(mono, 26),
            "hum_room":    ImageFont.truetype(mono, 18),
            "weather_sub": ImageFont.truetype(reg, 17),
            "fc_day":      ImageFont.truetype(bold, 15),
            "fc_temp":     ImageFont.truetype(mono, 14),
            "tiny":        ImageFont.truetype(reg, 12),
            "info":        ImageFont.truetype(reg, 11),
            "col_hdr":     ImageFont.truetype(bold, 13),
        }
    except OSError:
        log.warning("DejaVu fonts not found, using default")
        d = ImageFont.load_default()
        return {k: d for k in ["title","time","date","date_large","section","room_name","temp_outdoor","temp_big",
            "temp_room","hum_room","weather_sub","fc_day","fc_temp","tiny","info","col_hdr"]}

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  ICON DRAWING — clean vector-style for 1-bit e-paper                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class Icons:

    # ── Weather ─────────────────────────────────────────────

    @staticmethod
    def sun(draw, cx, cy, r=18):
        ir = int(r * 0.38)
        draw.ellipse([cx-ir, cy-ir, cx+ir, cy+ir], fill=0)
        for a in range(0, 360, 45):
            rad = math.radians(a)
            c, s = math.cos(rad), math.sin(rad)
            draw.line([cx+int((ir+4)*c), cy+int((ir+4)*s),
                       cx+int((r-1)*c),  cy+int((r-1)*s)], fill=0, width=2)

    @staticmethod
    def cloud(draw, cx, cy, r=18):
        bw, bh = int(r*1.5), int(r*0.65)
        # Fill shapes white first
        draw.ellipse([cx-bw//2, cy+1, cx+bw//2, cy+bh+1], fill=255)
        draw.ellipse([cx-bw//3-1, cy-int(r*0.45), cx+3, cy+5], fill=255)
        draw.ellipse([cx-3, cy-int(r*0.65), cx+bw//3+1, cy+3], fill=255)
        # Outlines
        draw.ellipse([cx-bw//2, cy+1, cx+bw//2, cy+bh+1], outline=0, width=2)
        draw.ellipse([cx-bw//3-1, cy-int(r*0.45), cx+3, cy+5], outline=0, width=2)
        draw.ellipse([cx-3, cy-int(r*0.65), cx+bw//3+1, cy+3], outline=0, width=2)
        # White-fill interior overlaps
        draw.ellipse([cx-bw//2+3, cy+3, cx+bw//2-3, cy+bh-1], fill=255)
        draw.ellipse([cx-bw//3+2, cy-int(r*0.45)+3, cx+1, cy+3], fill=255)
        draw.ellipse([cx-1, cy-int(r*0.65)+3, cx+bw//3-1, cy+1], fill=255)
        # Fill bottom overlap area
        draw.rectangle([cx-bw//3+4, cy+2, cx+bw//3-4, cy+6], fill=255)

    @staticmethod
    def partial_cloud(draw, cx, cy, r=18):
        Icons.sun(draw, cx-7, cy-7, r=int(r*0.55))
        Icons.cloud(draw, cx+4, cy+4, r=int(r*0.72))

    @staticmethod
    def _rain_drops(draw, cx, cy, n=3, length=8):
        sp = 10
        sx = cx - (n-1)*sp//2
        for i in range(n):
            x = sx + i*sp
            draw.line([x, cy, x-3, cy+length], fill=0, width=2)

    @staticmethod
    def rainy(draw, cx, cy, r=18):
        Icons.cloud(draw, cx, cy-7, r=int(r*0.78))
        Icons._rain_drops(draw, cx, cy+int(r*0.35), n=3, length=8)

    @staticmethod
    def pouring(draw, cx, cy, r=18):
        Icons.cloud(draw, cx, cy-7, r=int(r*0.78))
        Icons._rain_drops(draw, cx, cy+int(r*0.35), n=4, length=10)

    @staticmethod
    def snowy(draw, cx, cy, r=18):
        Icons.cloud(draw, cx, cy-7, r=int(r*0.78))
        sp = 12
        for i in range(3):
            sx = cx - sp + i*sp
            sy = cy + int(r*0.45)
            for a in range(0, 180, 60):
                rad = math.radians(a)
                d = 3
                draw.line([sx-int(d*math.cos(rad)), sy-int(d*math.sin(rad)),
                           sx+int(d*math.cos(rad)), sy+int(d*math.sin(rad))], fill=0, width=1)

    @staticmethod
    def thunderstorm(draw, cx, cy, r=18):
        Icons.cloud(draw, cx, cy-7, r=int(r*0.78))
        bolt = [(cx+1,cy+3),(cx-4,cy+11),(cx,cy+10),(cx-3,cy+17),
                (cx+5,cy+8),(cx+1,cy+9),(cx+4,cy+3)]
        draw.polygon(bolt, fill=0)

    @staticmethod
    def foggy(draw, cx, cy, r=18):
        for i in range(4):
            y = cy - 8 + i*7
            w = r - abs(i-1.5)*3
            draw.line([cx-int(w), y, cx+int(w), y], fill=0, width=2)

    @staticmethod
    def windy(draw, cx, cy, r=18):
        for i, (off, w) in enumerate([(-8,r+4),(0,r),(8,r-4)]):
            y = cy + off
            draw.arc([cx-int(w*0.7), y-3, cx+int(w*0.5), y+3], 180, 0, fill=0, width=2)

    @staticmethod
    def night(draw, cx, cy, r=18):
        draw.ellipse([cx-r//2, cy-r//2, cx+r//2, cy+r//2], fill=0)
        off = int(r*0.35)
        draw.ellipse([cx-r//2+off, cy-r//2-2, cx+r//2+off, cy+r//2-2], fill=255)

    @staticmethod
    def weather(draw, cx, cy, condition, r=18):
        c = condition.lower().replace("-","").replace("_","")
        if "lightning" in c or "thunder" in c: Icons.thunderstorm(draw, cx, cy, r)
        elif "pouring" in c:                   Icons.pouring(draw, cx, cy, r)
        elif "snow" in c:                      Icons.snowy(draw, cx, cy, r)
        elif "rain" in c:                      Icons.rainy(draw, cx, cy, r)
        elif "fog" in c or "mist" in c:        Icons.foggy(draw, cx, cy, r)
        elif "wind" in c:                      Icons.windy(draw, cx, cy, r)
        elif "partlycloudy" in c:              Icons.partial_cloud(draw, cx, cy, r)
        elif "cloud" in c:                     Icons.cloud(draw, cx, cy, r)
        elif "night" in c:                     Icons.night(draw, cx, cy, r)
        elif "sunny" in c or "clear" in c:     Icons.sun(draw, cx, cy, r)
        else:                                  Icons.cloud(draw, cx, cy, r)

    # ── Room icons ──────────────────────────────────────────

    @staticmethod
    def kitchen(d, cx, cy, s=11):
        """Fork + knife — universally readable."""
        fx = cx - 4
        d.line([fx, cy-s+1, fx, cy+s-1], fill=0, width=2)
        for dx in [-3, 0, 3]:
            d.line([fx+dx, cy-s+1, fx+dx, cy-s+6], fill=0, width=1)
        d.line([fx-3, cy-s+6, fx+3, cy-s+6], fill=0, width=1)
        kx = cx + 5
        d.line([kx, cy-s+1, kx, cy+s-1], fill=0, width=2)
        d.polygon([(kx, cy-s+1), (kx+5, cy-s+4), (kx+3, cy-3), (kx, cy-3)], fill=0)

    @staticmethod
    def livingroom(d, cx, cy, s=11):
        """Sofa — front view, clean lines."""
        d.rounded_rectangle([cx-s, cy-s+3, cx+s, cy+1], radius=3, outline=0, width=2)
        d.rounded_rectangle([cx-s, cy+1, cx+s, cy+6], radius=2, outline=0, width=2)
        d.rounded_rectangle([cx-s-3, cy-s+5, cx-s, cy+6], radius=2, fill=0)
        d.rounded_rectangle([cx+s, cy-s+5, cx+s+3, cy+6], radius=2, fill=0)
        d.line([cx-s+2, cy+6, cx-s+2, cy+9], fill=0, width=2)
        d.line([cx+s-2, cy+6, cx+s-2, cy+9], fill=0, width=2)

    @staticmethod
    def bedroom(d, cx, cy, s=11):
        """Bed — side view, solid headboard."""
        d.rectangle([cx-s, cy-2, cx+s, cy+5], outline=0, width=2)
        d.rectangle([cx-s, cy-s+1, cx-s+3, cy+5], fill=0)
        d.rounded_rectangle([cx-s+5, cy-1, cx-s+12, cy+3], radius=2, outline=0, width=2)
        d.line([cx, cy+1, cx+s-2, cy+1], fill=0, width=1)
        d.line([cx-s, cy+5, cx-s, cy+8], fill=0, width=2)
        d.line([cx+s, cy+5, cx+s, cy+8], fill=0, width=2)

    @staticmethod
    def childroom(d, cx, cy, s=11):
        """5-point star — clean, iconic."""
        points = []
        for i in range(10):
            a = math.radians(i * 36 - 90)
            r = (s - 1) if i % 2 == 0 else (s - 1) * 0.4
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(points, outline=0, width=2)

    @staticmethod
    def bathroom(d, cx, cy, s=11):
        """Bathtub — side view: basin + tall back + faucet + legs."""
        # Tub basin
        d.rounded_rectangle([cx-s+1, cy, cx+s-1, cy+s-1], radius=3, outline=0, width=2)
        # Tall back at left end (solid)
        d.rectangle([cx-s+1, cy-s+4, cx-s+5, cy+s-1], fill=0)
        # Faucet spout at top of back
        d.line([cx-s+5, cy-s+5, cx-s+10, cy-s+5], fill=0, width=2)
        # Legs
        d.line([cx-s+6, cy+s-1, cx-s+5, cy+s+3], fill=0, width=2)
        d.line([cx+s-4, cy+s-1, cx+s-4, cy+s+3], fill=0, width=2)

    @staticmethod
    def laundry(d, cx, cy, s=11):
        """Washing machine — front view, panel + drum."""
        d.rounded_rectangle([cx-s, cy-s, cx+s, cy+s], radius=2, outline=0, width=2)
        d.line([cx-s, cy-s+5, cx+s, cy-s+5], fill=0, width=1)
        for dx in [-5, -1, 3]:
            d.ellipse([cx+dx, cy-s+2, cx+dx+2, cy-s+4], fill=0)
        dr = s - 5
        d.ellipse([cx-dr, cy-dr+4, cx+dr, cy+dr+4], outline=0, width=2)

    @staticmethod
    def storage(d, cx, cy, s=11):
        """Cardboard box with flaps + tape."""
        d.rectangle([cx-s, cy-3, cx+s, cy+s-1], outline=0, width=2)
        d.line([cx-s, cy-3, cx-2, cy-7], fill=0, width=2)
        d.line([cx-2, cy-7, cx-2, cy-3], fill=0, width=2)
        d.line([cx+s, cy-3, cx+2, cy-7], fill=0, width=2)
        d.line([cx+2, cy-7, cx+2, cy-3], fill=0, width=2)
        d.line([cx, cy-3, cx, cy+s-2], fill=0, width=2)

    @staticmethod
    def room(draw, cx, cy, icon_type, s=11):
        fn = getattr(Icons, icon_type, None)
        if fn and icon_type not in ("weather","room","sun","cloud"):
            fn(draw, cx, cy, s)
        else:
            draw.rectangle([cx-s, cy-s+4, cx+s, cy+s-2], outline=0, width=2)
            draw.polygon([(cx-s-2, cy-s+4), (cx, cy-s-4), (cx+s+2, cy-s+4)], outline=0, width=2)


class IconAssets:
    def __init__(self, icons_dir: str = ""):
        env_dir = os.environ.get("EPD_ICONS_DIR", "")
        self.icons_dir = os.path.abspath(icons_dir or env_dir or DEFAULT_ICON_DIR)
        self.enabled = os.path.isdir(self.icons_dir)
        self._cache = {}
        if self.enabled:
            log.info(f"Using icon assets from: {self.icons_dir}")
        else:
            log.info("Icon assets directory not found; using built-in vector icons")

    @staticmethod
    def _variants(name: str):
        base = (name or "").strip().lower()
        variants = [
            base,
            base.replace("-", "_"),
            base.replace("_", "-"),
            base.replace("-", "").replace("_", ""),
        ]
        seen = set()
        out = []
        for v in variants:
            if v and v not in seen:
                out.append(v)
                seen.add(v)
        return out

    def _candidate_paths(self, category: str, name: str):
        for variant in self._variants(name):
            yield os.path.join(self.icons_dir, category, f"{variant}.png")
            yield os.path.join(self.icons_dir, f"{category}_{variant}.png")
            yield os.path.join(self.icons_dir, f"{variant}.png")

    def _load(self, category: str, name: str):
        cache_key = (category, name)
        if cache_key in self._cache:
            return self._cache[cache_key]
        for path in self._candidate_paths(category, name):
            if not os.path.exists(path):
                continue
            try:
                rgba = Image.open(path).convert("RGBA")
                flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                flat.alpha_composite(rgba)
                bw = flat.convert("L").point(lambda p: 0 if p < 140 else 255, mode="1")
                self._cache[cache_key] = bw
                return bw
            except Exception as e:
                log.warning(f"Failed to load icon asset {path}: {e}")
                break
        self._cache[cache_key] = None
        return None

    @staticmethod
    def _resample_filter():
        resampling = getattr(Image, "Resampling", None)
        return resampling.LANCZOS if resampling else Image.LANCZOS

    def draw(self, canvas: Image.Image, category: str, name: str, cx: int, cy: int, size: int) -> bool:
        if not self.enabled:
            return False
        icon = self._load(category, name)
        if icon is None:
            return False
        resized = icon.resize((size, size), self._resample_filter())
        x = int(cx - size / 2)
        y = int(cy - size / 2)
        canvas.paste(resized, (x, y))
        return True

    def draw_weather(self, canvas: Image.Image, condition: str, cx: int, cy: int, size: int) -> bool:
        condition_l = (condition or "unknown").lower()
        names = [condition_l]
        if "partlycloudy" in condition_l:
            names.extend(["partly_cloudy", "partly-cloudy"])
        if "clear-night" in condition_l:
            names.append("night")
        for name in names:
            if self.draw(canvas, "weather", name, cx, cy, size):
                return True
        return False

    def draw_room(self, canvas: Image.Image, icon_type: str, cx: int, cy: int, size: int) -> bool:
        return self.draw(canvas, "rooms", icon_type, cx, cy, size)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  HOME ASSISTANT API                                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _to_float_default(value, default: float) -> float:
    parsed = _to_float(value)
    return default if parsed is None else parsed


def _portrait_rect_to_epd_rect(rect, portrait_w: int, portrait_h: int):
    x0, y0, x1, y1 = rect
    x0 = max(0, min(portrait_w - 1, int(x0)))
    y0 = max(0, min(portrait_h - 1, int(y0)))
    x1 = max(x0 + 1, min(portrait_w, int(x1)))
    y1 = max(y0 + 1, min(portrait_h, int(y1)))

    def _map_point(px: int, py: int):
        # Image is rotated 90 degrees CCW before sending to the panel.
        return py, (portrait_w - 1) - px

    corners = [
        _map_point(x0, y0),
        _map_point(x1 - 1, y0),
        _map_point(x0, y1 - 1),
        _map_point(x1 - 1, y1 - 1),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def fetch_all_data(settings: DashboardSettings) -> dict:
    return fetch_all_data_from_ha(
        ha_url=settings.ha_url,
        ha_token=settings.ha_token,
        rooms=settings.rooms,
        weather_entity=settings.weather_entity,
        outdoor_temp=settings.outdoor_temp,
        outdoor_hum=settings.outdoor_hum,
        outdoor_uv=settings.outdoor_uv,
        outdoor_aqi=settings.outdoor_aqi,
        outdoor_pm25=settings.outdoor_pm25,
        sun_entity=settings.sun_entity,
        weather_alert_entity=settings.weather_alert_entity,
        dayparts_cache_file=settings.dayparts_cache_file,
        log=log,
    )

def demo_data() -> dict:
    today = datetime.now().date()
    forecast_days = [today + timedelta(days=offset) for offset in range(1, 5)]
    primary_onset = datetime.combine(today + timedelta(days=1), datetime.min.time()).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    primary_expires = primary_onset + timedelta(days=1, hours=12)
    secondary_onset = datetime.combine(today, datetime.min.time()).astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    secondary_expires = secondary_onset + timedelta(days=1, hours=13, minutes=59, seconds=59)
    return {
        "rooms": [
            {
                "name": "Cucina",
                "icon": "kitchen",
                "temp": 22.4,
                "hum": 48,
                "metrics": [
                    {"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 22.4, "raw": 22.4},
                    {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 48, "raw": 48},
                ],
            },
            {
                "name": "Soggiorno",
                "icon": "livingroom",
                "temp": 21.8,
                "hum": 45,
                "metrics": [
                    {"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 21.8, "raw": 21.8},
                    {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 45, "raw": 45},
                    {"key": "co2", "label": "CO2", "label_key": "co2", "unit": "ppm", "decimals": 0, "value": 612, "raw": 612},
                ],
            },
            {"name": "Camera",      "icon": "bedroom",    "temp": 20.3, "hum": 52, "metrics": [{"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 20.3, "raw": 20.3}, {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 52, "raw": 52}]},
            {"name": "Cameretta",   "icon": "childroom",  "temp": 21.0, "hum": 50, "metrics": [{"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 21.0, "raw": 21.0}, {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 50, "raw": 50}]},
            {"name": "Bagno",       "icon": "bathroom",   "temp": 23.1, "hum": 68, "metrics": [{"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 23.1, "raw": 23.1}, {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 68, "raw": 68}]},
            {"name": "Lavanderia",  "icon": "laundry",    "temp": 18.7, "hum": 62, "metrics": [{"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 18.7, "raw": 18.7}, {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 62, "raw": 62}]},
            {"name": "Sgabuzzino",  "icon": "storage",    "temp": 17.3, "hum": 55, "metrics": [{"key": "temp", "label": "", "label_key": "temp", "unit": "°", "decimals": 1, "value": 17.3, "raw": 17.3}, {"key": "hum", "label": "", "label_key": "hum", "unit": "%", "decimals": 0, "value": 55, "raw": 55}]},
        ],
        "weather": {
            "condition": "partlycloudy", "temperature": 8.2, "humidity": 72, "wind_speed": 12, "uv_index": 4.5,
            "dayparts": {
                "morning": {"min": 6.0, "max": 9.0, "condition": "cloudy"},
                "afternoon": {"min": 10.0, "max": 14.0, "condition": "partlycloudy"},
                "evening": {"min": 7.0, "max": 10.0, "condition": "rainy"},
            },
            "forecast": [
                {"datetime": forecast_days[0].isoformat(), "condition": "cloudy", "temperature": 11, "templow": 5},
                {"datetime": forecast_days[1].isoformat(), "condition": "sunny", "temperature": 13, "templow": 4},
                {"datetime": forecast_days[2].isoformat(), "condition": "snowy", "temperature": 4, "templow": -1},
                {"datetime": forecast_days[3].isoformat(), "condition": "rainy", "temperature": 8, "templow": 4},
            ],
            "alerts": [
                {
                    "event": "Yellow Wind Warning",
                    "severity": "Yellow",
                    "headline": "Yellow Wind Warning for Italy",
                    "onset": secondary_onset.isoformat(),
                    "expires": secondary_expires.isoformat(),
                    "type": "wind",
                },
                {
                    "event": "Orange Rain Warning",
                    "severity": "Orange",
                    "headline": "Orange Rain Warning for Italy",
                    "onset": primary_onset.isoformat(),
                    "expires": primary_expires.isoformat(),
                    "type": "rain",
                },
            ],
            "alert": {
                "event": "Orange Rain Warning",
                "severity": "Orange",
                "headline": "Orange Rain Warning for Italy",
                "onset": primary_onset.isoformat(),
                "expires": primary_expires.isoformat(),
                "type": "rain",
            }
        },
    }

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  RENDERER                                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def build_settings(config: dict, secrets: dict, require_secrets: bool) -> DashboardSettings:
    ha_url = str(secrets.get("ha_url", "")).strip()
    ha_token = str(secrets.get("ha_token", "")).strip()
    if require_secrets and (not ha_url or not ha_token):
        print("ERROR: secrets.json must contain non-empty 'ha_url' and 'ha_token'.")
        sys.exit(1)

    rooms_value = config.get("rooms", [])
    if not isinstance(rooms_value, list):
        log.warning("Invalid config.rooms: expected list, using empty list")
        rooms_value = []
    normalized_rooms = []
    for room in rooms_value:
        normalized_room = _normalize_room(room)
        if normalized_room:
            normalized_rooms.append(normalized_room)
    header_weekday_format = str(config.get("header_weekday_format", "full")).strip().lower()
    header_month_format = str(config.get("header_month_format", "full")).strip().lower()
    forecast_weekday_format = str(config.get("forecast_weekday_format", "abbr")).strip().lower()
    locale = str(config.get("locale", "en")).strip().lower() or "en"
    clock_daemon_interval_sec = _to_int(config.get("clock_daemon_interval_sec", 60), 60)
    blocks_value = config.get("blocks", ["outdoor", "forecast", "rooms", "footer"])
    if not isinstance(blocks_value, list):
        log.warning("Invalid config.blocks: expected list, using default order")
        blocks_value = ["outdoor", "forecast", "rooms", "footer"]
    full_every_cfg = config.get("clock_daemon_full_every_ticks", None)
    if full_every_cfg is None:
        full_every_cfg = config.get("clock_daemon_full_every", 240)
        if "clock_daemon_full_every" in config:
            log.warning(
                "config key 'clock_daemon_full_every' is deprecated; "
                "use 'clock_daemon_full_every_ticks' (unit: display ticks, not minutes)"
            )
    clock_daemon_full_every = _to_int(full_every_cfg, 240)
    clock_daemon_data_every_min = _to_int(config.get("clock_daemon_data_every_min", 10), 10)
    room_temp_min = _to_float_default(config.get("room_temp_min", 18.0), 18.0)
    room_temp_max = _to_float_default(config.get("room_temp_max", 24.0), 24.0)
    room_humidity_max = _to_float_default(config.get("room_humidity_max", 65.0), 65.0)

    if header_weekday_format not in ("full", "abbr"):
        log.warning("Invalid header_weekday_format in config.json, using 'full'")
        header_weekday_format = "full"
    if header_month_format not in ("full", "abbr"):
        log.warning("Invalid header_month_format in config.json, using 'full'")
        header_month_format = "full"
    if forecast_weekday_format not in ("full", "abbr"):
        log.warning("Invalid forecast_weekday_format in config.json, using 'abbr'")
        forecast_weekday_format = "abbr"

    allowed_blocks = {"outdoor", "forecast", "rooms", "footer"}
    normalized_blocks = []
    seen_blocks = set()
    for item in blocks_value:
        block_name = str(item).strip().lower()
        if block_name not in allowed_blocks:
            log.warning(f"Ignoring unknown block '{item}' in config.blocks")
            continue
        if block_name in seen_blocks:
            continue
        seen_blocks.add(block_name)
        normalized_blocks.append(block_name)
    if not normalized_blocks:
        normalized_blocks = ["outdoor", "forecast", "rooms", "footer"]

    i18n = load_i18n_bundle(locale, I18N_DIR, log)
    weekdays_abbr = i18n["weekdays_abbr"]
    weekdays_full = i18n["weekdays_full"]
    months_abbr = i18n["months_abbr"]
    months_full = i18n["months_full"]
    intraday_labels = i18n["intraday_labels"]
    condition_labels = i18n["condition_labels"]
    labels = i18n["labels"]
    if not isinstance(intraday_labels, list) or len(intraday_labels) != 3:
        intraday_labels = list(DEFAULT_I18N["intraday_labels"])
    fallback_quote = i18n["fallback_quote"] if isinstance(i18n.get("fallback_quote"), dict) else {}

    return DashboardSettings(
        ha_url=ha_url,
        ha_token=ha_token,
        rooms=normalized_rooms,
        weather_entity=str(config.get("weather_entity", "")).strip(),
        weather_alert_entity=str(config.get("weather_alert_entity", "")).strip(),
        outdoor_temp=str(config.get("outdoor_temp", "")).strip(),
        outdoor_hum=str(config.get("outdoor_hum", "")).strip(),
        outdoor_uv=str(config.get("outdoor_uv", "")).strip(),
        outdoor_aqi=str(config.get("outdoor_aqi", "")).strip(),
        outdoor_pm25=str(config.get("outdoor_pm25", "")).strip(),
        sun_entity=str(config.get("sun_entity", "sun.sun")).strip() or "sun.sun",
        footer_daily_quote=bool(config.get("footer_daily_quote", True)),
        footer_quote=str(config.get("footer_quote", "")).strip(),
        footer_source=str(config.get("footer_source", "")).strip(),
        quote_api_url=str(config.get("quote_api_url", "https://zenquotes.io/api/today")).strip(),
        quote_cache_file=str(config.get("quote_cache_file", "/tmp/epaper_daily_quote.json")).strip(),
        dayparts_cache_file=str(config.get("dayparts_cache_file", "/tmp/epaper_dayparts_cache.json")).strip(),
        header_weekday_format=header_weekday_format,
        header_month_format=header_month_format,
        forecast_weekday_format=forecast_weekday_format,
        locale=locale,
        header_title=str(config.get("header_title", "HOUSE")).strip() or "HOUSE",
        clock_partial_refresh=bool(config.get("clock_partial_refresh", True)),
        clock_partial_fullscreen=bool(config.get("clock_partial_fullscreen", True)),
        clock_daemon_interval_sec=clock_daemon_interval_sec,
        clock_daemon_full_every=clock_daemon_full_every,
        clock_daemon_data_every_min=clock_daemon_data_every_min,
        show_clock=bool(config.get("show_clock", True)),
        footer_debug_ticks=bool(config.get("footer_debug_ticks", False)),
        room_temp_min=room_temp_min,
        room_temp_max=room_temp_max,
        room_humidity_max=room_humidity_max,
        blocks=normalized_blocks,
        weekdays_abbr=weekdays_abbr,
        weekdays_full=weekdays_full,
        months_abbr=months_abbr,
        months_full=months_full,
        intraday_labels=intraday_labels,
        condition_labels=condition_labels,
        labels=labels,
        fallback_quote=(
            str(fallback_quote.get("text", DEFAULT_I18N["fallback_quote"]["text"])),
            str(fallback_quote.get("author", DEFAULT_I18N["fallback_quote"]["author"])),
        ),
    )


def _read_quote_cache(settings: DashboardSettings):
    try:
        with open(settings.quote_cache_file) as f:
            data = json.load(f)
        quote = (data.get("quote") or "").strip()
        author = (data.get("author") or "").strip()
        cached_date = (data.get("date") or "").strip()
        if quote and author and cached_date:
            return quote, author, cached_date
    except Exception:
        return None
    return None


def _write_quote_cache(settings: DashboardSettings, now: datetime, quote: str, author: str):
    try:
        with open(settings.quote_cache_file, "w") as f:
            json.dump(
                {"date": now.strftime("%Y-%m-%d"), "quote": quote, "author": author},
                f,
            )
    except Exception as e:
        log.warning(f"Failed to write quote cache {settings.quote_cache_file}: {e}")


def daily_quote(settings: DashboardSettings, now: datetime):
    today = now.strftime("%Y-%m-%d")
    cached = _read_quote_cache(settings)
    if cached and cached[2] == today:
        return cached[0], cached[1]

    try:
        r = requests.get(settings.quote_api_url, timeout=8)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data and isinstance(data[0], dict):
            quote = (data[0].get("q") or "").strip()
            author = (data[0].get("a") or "").strip()
            if quote and author:
                _write_quote_cache(settings, now, quote, author)
                return quote, author
    except Exception as e:
        log.warning(f"Failed to fetch daily quote from {settings.quote_api_url}: {e}")

    if cached:
        return cached[0], cached[1]
    if settings.footer_quote and settings.footer_source:
        return settings.footer_quote, settings.footer_source
    return settings.fallback_quote


def footer_text(settings: DashboardSettings, now: datetime):
    if settings.footer_daily_quote:
        return daily_quote(settings, now)
    return settings.footer_quote, settings.footer_source


def update_clock_header(img: Image.Image, settings: DashboardSettings, now: datetime = None):
    now = now or datetime.now()
    fonts = load_fonts()
    renderer_update_clock_header(
        img,
        now,
        width=W,
        header_h=HEADER_H,
        fonts=fonts,
        show_clock=settings.show_clock,
        header_title=settings.header_title,
        weekdays_full=settings.weekdays_full,
        weekdays_abbr=settings.weekdays_abbr,
        months_full=settings.months_full,
        months_abbr=settings.months_abbr,
        header_weekday_format=settings.header_weekday_format,
        header_month_format=settings.header_month_format,
    )


def load_cached_full_image(cache_image: str, settings: DashboardSettings) -> Image.Image:
    cache_path = os.path.abspath(os.path.expanduser(cache_image))
    try:
        img = Image.open(cache_path).convert("1")
        if img.size == (W, H):
            return img
        log.warning(f"Invalid cache image size {img.size}, expected {(W, H)}")
    except Exception as e:
        log.warning(f"Cache image unavailable ({cache_path}): {e}")
    img = Image.new("1", (W, H), 255)
    update_clock_header(img, settings)
    return img


def render(
    data: dict,
    settings: DashboardSettings,
    icon_assets,
    now: datetime = None,
    last_updated: datetime = None,
    footer_debug_text: str = "",
) -> Image.Image:
    now = now or datetime.now()
    fonts = load_fonts()
    return render_dashboard(
        data,
        now,
        width=W,
        height=H,
        header_h=HEADER_H,
        fonts=fonts,
        icon_assets=icon_assets,
        icons_cls=Icons,
        condition_labels=settings.condition_labels,
        intraday_labels=settings.intraday_labels,
        labels=settings.labels,
        blocks=settings.blocks,
        weekdays_full=settings.weekdays_full,
        weekdays_abbr=settings.weekdays_abbr,
        months_full=settings.months_full,
        months_abbr=settings.months_abbr,
        header_weekday_format=settings.header_weekday_format,
        header_month_format=settings.header_month_format,
        forecast_weekday_format=settings.forecast_weekday_format,
        show_clock=settings.show_clock,
        header_title=settings.header_title,
        footer_text_fn=lambda footer_now: footer_text(settings, footer_now),
        last_updated=last_updated,
        footer_debug_text=footer_debug_text,
        room_temp_min=settings.room_temp_min,
        room_temp_max=settings.room_temp_max,
        room_humidity_max=settings.room_humidity_max,
    )

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  E-PAPER OUTPUT                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝


def send_to_epaper(
    img: Image.Image,
    epd_lib_path: str = "",
    mode: str = "full",
    clock_partial_refresh: bool = False,
):
    epd_send_to_epaper(
        img,
        epd_lib_path=epd_lib_path,
        mode=mode,
        clock_partial_refresh=clock_partial_refresh,
        script_dir=SCRIPT_DIR,
        log=log,
    )


def run_clock_daemon(
    settings: DashboardSettings,
    icon_assets,
    epd_lib_path: str,
    cache_image: str,
    interval_sec: int,
    full_every: int,
    data_every_min: int,
    partial_refresh: bool,
    partial_fullscreen: bool,
    demo: bool,
):
    epd_driver = load_epd_driver(epd_lib_path, SCRIPT_DIR, log)
    epd = epd_driver.EPD()
    init_partial_fn, init_name = first_callable(epd, ["init_part", "init_fast", "init_Fast", "init"])
    disp_partial_fn, disp_name = first_callable(epd, ["displayPartial", "display_partial", "display_Partial"])
    partial_enabled = bool(partial_refresh and init_partial_fn and disp_partial_fn)
    if partial_enabled:
        log.info(f"Clock daemon partial enabled ({init_name} + {disp_name})")
    else:
        log.warning("Clock daemon running without partial refresh (set clock_partial_refresh=true)")

    interval_sec = max(1, int(interval_sec))
    full_every = max(1, int(full_every))
    data_every_min = max(1, int(data_every_min))
    data_every_ticks = max(1, int(round((data_every_min * 60) / interval_sec)))
    clock_header_rect_epd = _portrait_rect_to_epd_rect((0, 0, W, HEADER_H), W, H)

    tick_count = 0
    display_tick_count = 0
    ticks_since_full = 0
    last_data_snapshot = None
    last_date = datetime.now().date()
    img = load_cached_full_image(cache_image, settings)
    try:
        initial_data = demo_data() if demo else fetch_all_data(settings)
        init_now = datetime.now()
        startup_debug_text = "0" if settings.footer_debug_ticks else ""
        img = render(initial_data, settings, icon_assets, now=init_now, last_updated=init_now, footer_debug_text=startup_debug_text)
        last_data_snapshot = build_data_snapshot(
            initial_data,
            _to_float,
            room_temp_min=settings.room_temp_min,
            room_temp_max=settings.room_temp_max,
            room_humidity_max=settings.room_humidity_max,
        )
    except Exception as e:
        log.warning(f"Initial render failed, using cached image: {e}")
        update_clock_header(img, settings)
    last_frame_img = img.copy()
    if settings.show_clock:
        log.info(
            f"Clock daemon started (clock every {interval_sec}s, data every {data_every_min}m, "
            f"full every {full_every} ticks)"
        )
    else:
        log.info(
            f"Clock disabled in config: refreshing data every {data_every_min}m "
            f"(full every {full_every} display ticks)"
        )

    # Force an immediate full draw at startup so date and Last updated are fresh.
    try:
        img.save(cache_image, "PNG")
    except Exception as e:
        log.warning(f"Failed to update cache image {cache_image}: {e}")
    startup_buffer = epd.getbuffer(img.rotate(90, expand=True))
    epd.init()
    epd.display(startup_buffer)
    last_frame_img = img.copy()
    display_tick_count = 1
    tick_count = 1

    try:
        while True:
            now = datetime.now()
            try:
                day_changed = now.date() != last_date
                do_data = tick_count == 0 or (tick_count % data_every_ticks == 0) or day_changed
                if day_changed:
                    log.info("Day changed, forcing data refresh")
                    last_date = now.date()
                do_clock_tick = bool(settings.show_clock and not do_data)

                if not do_data and not do_clock_tick:
                    tick_count += 1
                    now_ts = time.time()
                    sleep_s = max(0.1, interval_sec - (now_ts % interval_sec))
                    time.sleep(sleep_s)
                    continue

                do_full = display_tick_count == 0 or (display_tick_count % full_every == 0) or day_changed
                debug_tick_value = 0 if do_full else (ticks_since_full + 1)
                debug_text = str(debug_tick_value) if settings.footer_debug_ticks else ""

                if do_data:
                    data = demo_data() if demo else fetch_all_data(settings)
                    new_img = render(data, settings, icon_assets, now=now, last_updated=now, footer_debug_text=debug_text)
                    curr_snapshot = build_data_snapshot(
                        data,
                        _to_float,
                        room_temp_min=settings.room_temp_min,
                        room_temp_max=settings.room_temp_max,
                        room_humidity_max=settings.room_humidity_max,
                    )
                    changed = diff_snapshots(last_data_snapshot, curr_snapshot)
                    has_data_change = bool(
                        changed.get("outdoor")
                        or changed.get("intraday")
                        or changed.get("forecast")
                        or changed.get("alert")
                        or changed.get("rooms")
                    )
                    data_rects = build_dynamic_partial_rects(data, HEADER_H, W, H, changed=changed)
                    if do_full or last_frame_img is None:
                        img = new_img
                    else:
                        img = last_frame_img.copy()
                        for rect in data_rects:
                            x0, y0, x1, y1 = rect
                            img.paste(new_img.crop((x0, y0, x1, y1)), (x0, y0))
                    last_data_snapshot = curr_snapshot
                else:
                    img = last_frame_img.copy()
                    update_clock_header(img, settings, now=now)
                    if settings.footer_debug_ticks:
                        draw = ImageDraw.Draw(img)
                        fonts = load_fonts()
                        draw.text((W - 3, H - 1), debug_text, fill=0, font=fonts["tiny"], anchor="rd")

                if do_full:
                    try:
                        img.save(cache_image, "PNG")
                    except Exception as e:
                        log.warning(f"Failed to update cache image {cache_image}: {e}")
                buffer = epd.getbuffer(img.rotate(90, expand=True))

                if do_full:
                    epd.init()
                    epd.display(buffer)
                elif partial_enabled:
                    init_partial_fn()
                    if do_data:
                        if partial_fullscreen:
                            partial_ok = safe_partial_refresh(epd, disp_partial_fn, buffer, rect=None)
                            if not partial_ok:
                                log.warning("Data partial refresh failed, switching to full refresh")
                                partial_enabled = False
                                epd.init()
                                epd.display(buffer)
                        else:
                            # Conservative mode: avoid data partial updates when fullscreen partial is disabled.
                            # On some panel/driver combinations rect partials are unstable and corrupt the frame.
                            # To reduce full refresh frequency, skip refresh when non-clock data did not change.
                            if has_data_change:
                                epd.init()
                                epd.display(buffer)
                            else:
                                log.info("No data change detected, skipping data-tick display refresh")
                    elif not safe_partial_refresh(epd, disp_partial_fn, buffer, rect=clock_header_rect_epd):
                        log.warning("Clock daemon partial failed, switching to full refresh")
                        partial_enabled = False
                        epd.init()
                        epd.display(buffer)
                else:
                    epd.init()
                    epd.display(buffer)

                last_frame_img = img.copy()
                ticks_since_full = 0 if do_full else debug_tick_value
                display_tick_count += 1
                tick_count += 1
            except Exception as e:
                log.warning(f"Clock daemon tick failed: {e}")
                tick_count += 1

            now_ts = time.time()
            sleep_s = max(0.1, interval_sec - (now_ts % interval_sec))
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        log.info("Clock daemon stopped")
    finally:
        try:
            epd.sleep()
        except Exception:
            pass

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAIN                                                                    ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def main():
    parser = argparse.ArgumentParser(description="HA e-Paper Dashboard")
    parser.add_argument("--simulate", action="store_true", help="Save PNG instead of driving e-paper")
    parser.add_argument("--demo", action="store_true", help="Use demo data instead of fetching from HA")
    parser.add_argument("--output", default="/tmp/epaper_dashboard.png", help="PNG output path")
    parser.add_argument(
        "--mode",
        choices=["full", "clock", "clock-daemon"],
        default="full",
        help="full: all data, clock: header only oneshot, clock-daemon: continuous clock updates",
    )
    parser.add_argument("--epd-lib-path", default="", help="Path to Waveshare python lib dir")
    parser.add_argument("--icons-dir", default="", help="Path to icon assets directory")
    parser.add_argument(
        "--clock-partial-refresh",
        action="store_true",
        help="Enable partial refresh in clock/clock-daemon mode (can cause artifacts on some panels)",
    )
    parser.add_argument("--cache-image", default="/tmp/epaper_dashboard_full.png",
                        help="Cached full image used by clock mode")
    parser.add_argument(
        "--clock-interval-sec",
        type=int,
        default=60,
        help="Clock daemon tick interval (seconds)",
    )
    parser.add_argument(
        "--clock-full-every",
        "--clock-full-every-ticks",
        dest="clock_full_every",
        type=int,
        default=240,
        help="Clock daemon force full refresh every N display ticks (not minutes)",
    )
    parser.add_argument(
        "--clock-data-every-min",
        type=int,
        default=10,
        help="Clock daemon refresh non-clock data every N minutes",
    )
    args = parser.parse_args()

    require_ha_credentials = (not args.demo) and args.mode in ("full", "clock-daemon")
    config_required = require_ha_credentials
    config = _load_json("config.json", required=config_required)
    secrets = _load_json("secrets.json", required=require_ha_credentials)
    settings = build_settings(config, secrets, require_secrets=require_ha_credentials)

    if "--clock-interval-sec" not in sys.argv:
        args.clock_interval_sec = settings.clock_daemon_interval_sec
    if "--clock-full-every" not in sys.argv and "--clock-full-every-ticks" not in sys.argv:
        args.clock_full_every = settings.clock_daemon_full_every
    if "--clock-data-every-min" not in sys.argv:
        args.clock_data_every_min = settings.clock_daemon_data_every_min

    icon_assets = IconAssets(args.icons_dir)
    args.clock_interval_sec = max(1, int(args.clock_interval_sec))
    args.clock_full_every = max(1, int(args.clock_full_every))
    args.clock_data_every_min = max(1, int(args.clock_data_every_min))

    if args.mode == "clock-daemon":
        run_clock_daemon(
            settings=settings,
            icon_assets=icon_assets,
            epd_lib_path=args.epd_lib_path,
            cache_image=args.cache_image,
            interval_sec=args.clock_interval_sec,
            full_every=args.clock_full_every,
            data_every_min=args.clock_data_every_min,
            partial_refresh=args.clock_partial_refresh or bool(settings.clock_partial_refresh),
            partial_fullscreen=bool(settings.clock_partial_fullscreen),
            demo=args.demo,
        )
        return

    if args.mode == "clock":
        log.info("Clock-only mode: reusing cached full image")
        img = load_cached_full_image(args.cache_image, settings)
        update_clock_header(img, settings)
    else:
        if args.demo:
            log.info("Using demo data")
            data = demo_data()
        else:
            log.info("Fetching from Home Assistant...")
            data = fetch_all_data(settings)

        log.info("Rendering...")
        now = datetime.now()
        debug_text = "0" if settings.footer_debug_ticks else ""
        img = render(data, settings, icon_assets, now=now, last_updated=now, footer_debug_text=debug_text)
        try:
            img.save(args.cache_image, "PNG")
        except Exception as e:
            log.warning(f"Failed to update cache image {args.cache_image}: {e}")

    if args.simulate:
        img.save(args.output, "PNG")
        log.info(f"Preview: {args.output}")
    else:
        clock_partial_refresh = args.clock_partial_refresh or bool(settings.clock_partial_refresh)
        send_to_epaper(
            img,
            args.epd_lib_path,
            mode=args.mode,
            clock_partial_refresh=clock_partial_refresh,
        )
        log.info("Done!")

if __name__ == "__main__":
    main()
