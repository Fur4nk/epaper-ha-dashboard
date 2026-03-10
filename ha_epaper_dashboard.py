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
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
from dashboard_ha import fetch_all_data as fetch_all_data_from_ha
from dashboard_epd import (
    first_callable,
    load_epd_driver,
    partial_refresh_rects,
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


HA_URL = ""
HA_TOKEN = ""
ROOMS = []
WEATHER_ENTITY = ""
OUTDOOR_TEMP = ""
OUTDOOR_HUM = ""
OUTDOOR_UV = ""
OUTDOOR_AQI = ""
OUTDOOR_PM25 = ""
SUN_ENTITY = "sun.sun"
FOOTER_DAILY_QUOTE = True
FOOTER_QUOTE = ""
FOOTER_SOURCE = ""
QUOTE_API_URL = "https://zenquotes.io/api/today"
QUOTE_CACHE_FILE = "/tmp/epaper_daily_quote.json"
DAYPARTS_CACHE_FILE = "/tmp/epaper_dayparts_cache.json"
HEADER_WEEKDAY_FORMAT = "full"
HEADER_MONTH_FORMAT = "full"
FORECAST_WEEKDAY_FORMAT = "abbr"
LOCALE = "en"
I18N_DIR = os.path.join(SCRIPT_DIR, "i18n")
HEADER_TITLE = "HOUSE"
CLOCK_PARTIAL_REFRESH = True
CLOCK_PARTIAL_FULLSCREEN = True
CLOCK_DAEMON_INTERVAL_SEC = 60
CLOCK_DAEMON_FULL_EVERY = 240
CLOCK_DAEMON_DATA_EVERY_MIN = 10
SHOW_CLOCK = True

W, H = 480, 800
HEADER_H = 56

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
DEFAULT_ICON_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")
ICON_ASSETS = None

WEEKDAYS_ABBR = DEFAULT_I18N["weekdays_abbr"]
WEEKDAYS_FULL = DEFAULT_I18N["weekdays_full"]
MONTHS_ABBR = DEFAULT_I18N["months_abbr"]
MONTHS_FULL = DEFAULT_I18N["months_full"]
INTRADAY_LABELS = DEFAULT_I18N["intraday_labels"]
CONDITION_LABELS = DEFAULT_I18N["condition_labels"]
LABELS = DEFAULT_I18N["labels"]
FALLBACK_QUOTE = (
    str(DEFAULT_I18N["fallback_quote"]["text"]),
    str(DEFAULT_I18N["fallback_quote"]["author"]),
)

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
            "title":       ImageFont.truetype(bold, 30),
            "time":        ImageFont.truetype(mono, 30),
            "date":        ImageFont.truetype(reg, 14),
            "date_large":  ImageFont.truetype(bold, 16),
            "section":     ImageFont.truetype(bold, 13),
            "room_name":   ImageFont.truetype(bold, 19),
            "temp_outdoor": ImageFont.truetype(mono, 40),
            "temp_big":    ImageFont.truetype(mono, 32),
            "temp_room":   ImageFont.truetype(mono, 24),
            "hum_room":    ImageFont.truetype(mono, 16),
            "weather_sub": ImageFont.truetype(reg, 14),
            "fc_day":      ImageFont.truetype(bold, 13),
            "fc_temp":     ImageFont.truetype(mono, 12),
            "tiny":        ImageFont.truetype(reg, 10),
            "col_hdr":     ImageFont.truetype(bold, 11),
        }
    except OSError:
        log.warning("DejaVu fonts not found, using default")
        d = ImageFont.load_default()
        return {k: d for k in ["title","time","date","date_large","section","room_name","temp_outdoor","temp_big",
            "temp_room","hum_room","weather_sub","fc_day","fc_temp","tiny","col_hdr"]}

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


def fetch_all_data() -> dict:
    return fetch_all_data_from_ha(
        ha_url=HA_URL,
        ha_token=HA_TOKEN,
        rooms=ROOMS,
        weather_entity=WEATHER_ENTITY,
        outdoor_temp=OUTDOOR_TEMP,
        outdoor_hum=OUTDOOR_HUM,
        outdoor_uv=OUTDOOR_UV,
        outdoor_aqi=OUTDOOR_AQI,
        outdoor_pm25=OUTDOOR_PM25,
        sun_entity=SUN_ENTITY,
        dayparts_cache_file=DAYPARTS_CACHE_FILE,
        log=log,
    )

def demo_data() -> dict:
    return {
        "rooms": [
            {"name": "Cucina",      "icon": "kitchen",    "temp": 22.4, "hum": 48},
            {"name": "Soggiorno",   "icon": "livingroom", "temp": 21.8, "hum": 45},
            {"name": "Camera",      "icon": "bedroom",    "temp": 20.3, "hum": 52},
            {"name": "Cameretta",   "icon": "childroom",  "temp": 21.0, "hum": 50},
            {"name": "Bagno",       "icon": "bathroom",   "temp": 23.1, "hum": 68},
            {"name": "Lavanderia",  "icon": "laundry",    "temp": 18.7, "hum": 62},
            {"name": "Sgabuzzino",  "icon": "storage",    "temp": 17.3, "hum": 55},
        ],
        "weather": {
            "condition": "partlycloudy", "temperature": 8.2, "humidity": 72, "wind_speed": 12,
            "dayparts": {
                "morning": {"temperature": 7.0, "condition": "cloudy"},
                "afternoon": {"temperature": 12.0, "condition": "partlycloudy"},
                "evening": {"temperature": 9.0, "condition": "rainy"},
            },
            "forecast": [
                {"datetime": "2026-02-24", "condition": "rainy",        "temperature": 9,  "templow": 3},
                {"datetime": "2026-02-25", "condition": "cloudy",       "temperature": 11, "templow": 5},
                {"datetime": "2026-02-26", "condition": "sunny",        "temperature": 13, "templow": 4},
                {"datetime": "2026-02-27", "condition": "snowy",        "temperature": 4,  "templow": -1},
            ],
        },
    }

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  RENDERER                                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def configure_runtime(config: dict, secrets: dict, require_secrets: bool):
    global HA_URL, HA_TOKEN, ROOMS, WEATHER_ENTITY, OUTDOOR_TEMP, OUTDOOR_HUM, OUTDOOR_UV
    global OUTDOOR_AQI, OUTDOOR_PM25, SUN_ENTITY, FOOTER_DAILY_QUOTE, FOOTER_QUOTE, FOOTER_SOURCE
    global QUOTE_API_URL, QUOTE_CACHE_FILE, DAYPARTS_CACHE_FILE, HEADER_WEEKDAY_FORMAT, HEADER_MONTH_FORMAT
    global FORECAST_WEEKDAY_FORMAT, LOCALE, HEADER_TITLE, CLOCK_PARTIAL_REFRESH, CLOCK_PARTIAL_FULLSCREEN
    global CLOCK_DAEMON_INTERVAL_SEC, CLOCK_DAEMON_FULL_EVERY, CLOCK_DAEMON_DATA_EVERY_MIN, SHOW_CLOCK
    global WEEKDAYS_ABBR, WEEKDAYS_FULL, MONTHS_ABBR, MONTHS_FULL, INTRADAY_LABELS, CONDITION_LABELS, LABELS
    global FALLBACK_QUOTE

    HA_URL = str(secrets.get("ha_url", "")).strip()
    HA_TOKEN = str(secrets.get("ha_token", "")).strip()
    if require_secrets and (not HA_URL or not HA_TOKEN):
        print("ERROR: secrets.json must contain non-empty 'ha_url' and 'ha_token'.")
        sys.exit(1)

    rooms_value = config.get("rooms", [])
    if not isinstance(rooms_value, list):
        log.warning("Invalid config.rooms: expected list, using empty list")
        rooms_value = []
    ROOMS = rooms_value
    WEATHER_ENTITY = str(config.get("weather_entity", "")).strip()
    OUTDOOR_TEMP = str(config.get("outdoor_temp", "")).strip()
    OUTDOOR_HUM = str(config.get("outdoor_hum", "")).strip()
    OUTDOOR_UV = str(config.get("outdoor_uv", "")).strip()
    OUTDOOR_AQI = str(config.get("outdoor_aqi", "")).strip()
    OUTDOOR_PM25 = str(config.get("outdoor_pm25", "")).strip()
    SUN_ENTITY = str(config.get("sun_entity", "sun.sun")).strip() or "sun.sun"
    FOOTER_DAILY_QUOTE = bool(config.get("footer_daily_quote", True))
    FOOTER_QUOTE = str(config.get("footer_quote", "")).strip()
    FOOTER_SOURCE = str(config.get("footer_source", "")).strip()
    QUOTE_API_URL = str(config.get("quote_api_url", "https://zenquotes.io/api/today")).strip()
    QUOTE_CACHE_FILE = str(config.get("quote_cache_file", "/tmp/epaper_daily_quote.json")).strip()
    DAYPARTS_CACHE_FILE = str(config.get("dayparts_cache_file", "/tmp/epaper_dayparts_cache.json")).strip()
    HEADER_WEEKDAY_FORMAT = str(config.get("header_weekday_format", "full")).strip().lower()
    HEADER_MONTH_FORMAT = str(config.get("header_month_format", "full")).strip().lower()
    FORECAST_WEEKDAY_FORMAT = str(config.get("forecast_weekday_format", "abbr")).strip().lower()
    LOCALE = str(config.get("locale", "en")).strip().lower() or "en"
    HEADER_TITLE = str(config.get("header_title", "HOUSE")).strip() or "HOUSE"
    CLOCK_PARTIAL_REFRESH = bool(config.get("clock_partial_refresh", True))
    CLOCK_PARTIAL_FULLSCREEN = bool(config.get("clock_partial_fullscreen", True))
    CLOCK_DAEMON_INTERVAL_SEC = _to_int(config.get("clock_daemon_interval_sec", 60), 60)
    full_every_cfg = config.get("clock_daemon_full_every_ticks", None)
    if full_every_cfg is None:
        full_every_cfg = config.get("clock_daemon_full_every", 240)
        if "clock_daemon_full_every" in config:
            log.warning(
                "config key 'clock_daemon_full_every' is deprecated; "
                "use 'clock_daemon_full_every_ticks' (unit: display ticks, not minutes)"
            )
    CLOCK_DAEMON_FULL_EVERY = _to_int(full_every_cfg, 240)
    CLOCK_DAEMON_DATA_EVERY_MIN = _to_int(config.get("clock_daemon_data_every_min", 10), 10)
    SHOW_CLOCK = bool(config.get("show_clock", True))

    if HEADER_WEEKDAY_FORMAT not in ("full", "abbr"):
        log.warning("Invalid header_weekday_format in config.json, using 'full'")
        HEADER_WEEKDAY_FORMAT = "full"
    if HEADER_MONTH_FORMAT not in ("full", "abbr"):
        log.warning("Invalid header_month_format in config.json, using 'full'")
        HEADER_MONTH_FORMAT = "full"
    if FORECAST_WEEKDAY_FORMAT not in ("full", "abbr"):
        log.warning("Invalid forecast_weekday_format in config.json, using 'abbr'")
        FORECAST_WEEKDAY_FORMAT = "abbr"

    i18n = load_i18n_bundle(LOCALE, I18N_DIR, log)
    WEEKDAYS_ABBR = i18n["weekdays_abbr"]
    WEEKDAYS_FULL = i18n["weekdays_full"]
    MONTHS_ABBR = i18n["months_abbr"]
    MONTHS_FULL = i18n["months_full"]
    INTRADAY_LABELS = i18n["intraday_labels"]
    CONDITION_LABELS = i18n["condition_labels"]
    LABELS = i18n["labels"]
    if not isinstance(INTRADAY_LABELS, list) or len(INTRADAY_LABELS) != 3:
        INTRADAY_LABELS = list(DEFAULT_I18N["intraday_labels"])
    fallback_quote = i18n["fallback_quote"] if isinstance(i18n.get("fallback_quote"), dict) else {}
    FALLBACK_QUOTE = (
        str(fallback_quote.get("text", DEFAULT_I18N["fallback_quote"]["text"])),
        str(fallback_quote.get("author", DEFAULT_I18N["fallback_quote"]["author"])),
    )


def _read_quote_cache():
    try:
        with open(QUOTE_CACHE_FILE) as f:
            data = json.load(f)
        quote = (data.get("quote") or "").strip()
        author = (data.get("author") or "").strip()
        cached_date = (data.get("date") or "").strip()
        if quote and author and cached_date:
            return quote, author, cached_date
    except Exception:
        return None
    return None


def _write_quote_cache(now: datetime, quote: str, author: str):
    try:
        with open(QUOTE_CACHE_FILE, "w") as f:
            json.dump(
                {"date": now.strftime("%Y-%m-%d"), "quote": quote, "author": author},
                f,
            )
    except Exception as e:
        log.warning(f"Failed to write quote cache {QUOTE_CACHE_FILE}: {e}")


def daily_quote(now: datetime):
    today = now.strftime("%Y-%m-%d")
    cached = _read_quote_cache()
    if cached and cached[2] == today:
        return cached[0], cached[1]

    try:
        r = requests.get(QUOTE_API_URL, timeout=8)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data and isinstance(data[0], dict):
            quote = (data[0].get("q") or "").strip()
            author = (data[0].get("a") or "").strip()
            if quote and author:
                _write_quote_cache(now, quote, author)
                return quote, author
    except Exception as e:
        log.warning(f"Failed to fetch daily quote from {QUOTE_API_URL}: {e}")

    if cached:
        return cached[0], cached[1]
    if FOOTER_QUOTE and FOOTER_SOURCE:
        return FOOTER_QUOTE, FOOTER_SOURCE
    return FALLBACK_QUOTE


def footer_text(now: datetime):
    if FOOTER_DAILY_QUOTE:
        return daily_quote(now)
    return FOOTER_QUOTE, FOOTER_SOURCE


def update_clock_header(img: Image.Image, now: datetime = None):
    now = now or datetime.now()
    fonts = load_fonts()
    renderer_update_clock_header(
        img,
        now,
        width=W,
        header_h=HEADER_H,
        fonts=fonts,
        show_clock=SHOW_CLOCK,
        header_title=HEADER_TITLE,
        weekdays_full=WEEKDAYS_FULL,
        weekdays_abbr=WEEKDAYS_ABBR,
        months_full=MONTHS_FULL,
        months_abbr=MONTHS_ABBR,
        header_weekday_format=HEADER_WEEKDAY_FORMAT,
        header_month_format=HEADER_MONTH_FORMAT,
    )


def load_cached_full_image(cache_image: str) -> Image.Image:
    cache_path = os.path.abspath(os.path.expanduser(cache_image))
    try:
        img = Image.open(cache_path).convert("1")
        if img.size == (W, H):
            return img
        log.warning(f"Invalid cache image size {img.size}, expected {(W, H)}")
    except Exception as e:
        log.warning(f"Cache image unavailable ({cache_path}): {e}")
    img = Image.new("1", (W, H), 255)
    update_clock_header(img)
    return img


def render(data: dict, now: datetime = None, last_updated: datetime = None) -> Image.Image:
    now = now or datetime.now()
    fonts = load_fonts()
    return render_dashboard(
        data,
        now,
        width=W,
        height=H,
        header_h=HEADER_H,
        fonts=fonts,
        icon_assets=ICON_ASSETS,
        icons_cls=Icons,
        condition_labels=CONDITION_LABELS,
        intraday_labels=INTRADAY_LABELS,
        labels=LABELS,
        weekdays_full=WEEKDAYS_FULL,
        weekdays_abbr=WEEKDAYS_ABBR,
        months_full=MONTHS_FULL,
        months_abbr=MONTHS_ABBR,
        header_weekday_format=HEADER_WEEKDAY_FORMAT,
        header_month_format=HEADER_MONTH_FORMAT,
        forecast_weekday_format=FORECAST_WEEKDAY_FORMAT,
        show_clock=SHOW_CLOCK,
        header_title=HEADER_TITLE,
        footer_text_fn=footer_text,
        last_updated=last_updated,
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
    last_data_snapshot = None
    startup_data_ok = False
    last_data_updated_at = None
    img = load_cached_full_image(cache_image)
    try:
        initial_data = demo_data() if demo else fetch_all_data()
        init_now = datetime.now()
        img = render(initial_data, now=init_now, last_updated=init_now)
        last_data_snapshot = build_data_snapshot(initial_data, _to_float)
        startup_data_ok = True
        last_data_updated_at = init_now
    except Exception as e:
        log.warning(f"Initial render failed, using cached image: {e}")
    last_frame_img = img.copy()
    if SHOW_CLOCK:
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
    tick_count = 0

    try:
        while True:
            now = datetime.now()
            try:
                do_data = (not startup_data_ok) or tick_count == 0 or (tick_count % data_every_ticks == 0)
                do_clock_tick = bool(SHOW_CLOCK and not do_data)

                if not do_data and not do_clock_tick:
                    tick_count += 1
                    now_ts = time.time()
                    sleep_s = max(0.1, interval_sec - (now_ts % interval_sec))
                    time.sleep(sleep_s)
                    continue

                do_full = display_tick_count == 0 or (display_tick_count % full_every == 0)

                if do_data:
                    data = demo_data() if demo else fetch_all_data()
                    curr_snapshot = build_data_snapshot(data, _to_float)
                    changed = diff_snapshots(last_data_snapshot, curr_snapshot)
                    has_data_change = bool(
                        changed.get("outdoor")
                        or changed.get("intraday")
                        or changed.get("forecast")
                        or changed.get("rooms")
                    )
                    if has_data_change:
                        last_data_updated_at = now

                    new_img = render(data, now=now, last_updated=last_data_updated_at)
                    data_rects = build_dynamic_partial_rects(data, HEADER_H, W, H, changed=changed)
                    data_rects_epd = [
                        _portrait_rect_to_epd_rect(rect, W, H)
                        for rect in data_rects
                    ]
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
                    update_clock_header(img, now=now)

                if do_full:
                    try:
                        img.save(cache_image, "PNG")
                    except Exception as e:
                        log.warning(f"Failed to update cache image {cache_image}: {e}")
                buffer = epd.getbuffer(img.rotate(90, expand=True))
                did_display = False

                if do_full:
                    epd.init()
                    epd.display(buffer)
                    did_display = True
                elif partial_enabled:
                    init_partial_fn()
                    if do_data:
                        if partial_fullscreen:
                            partial_ok = safe_partial_refresh(epd, disp_partial_fn, buffer, rect=None)
                            did_display = partial_ok
                            if not partial_ok:
                                log.warning("Data partial refresh failed, switching to full refresh")
                                partial_enabled = False
                                epd.init()
                                epd.display(buffer)
                                did_display = True
                        else:
                            if has_data_change:
                                partial_ok = partial_refresh_rects(epd, disp_partial_fn, buffer, data_rects_epd)
                                did_display = partial_ok
                                if not partial_ok:
                                    log.warning("Data rect partial refresh failed, switching to full refresh")
                                    partial_enabled = False
                                    epd.init()
                                    epd.display(buffer)
                                    did_display = True
                            else:
                                log.info("No data change detected, skipping data-tick display refresh")
                    else:
                        partial_ok = safe_partial_refresh(epd, disp_partial_fn, buffer, rect=clock_header_rect_epd)
                        did_display = partial_ok
                        if not partial_ok:
                            log.warning("Clock daemon partial failed, switching to full refresh")
                            partial_enabled = False
                            epd.init()
                            epd.display(buffer)
                            did_display = True
                else:
                    epd.init()
                    epd.display(buffer)
                    did_display = True

                if do_data:
                    startup_data_ok = True

                if did_display:
                    last_frame_img = img.copy()
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
    global ICON_ASSETS
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
        default=CLOCK_DAEMON_INTERVAL_SEC,
        help="Clock daemon tick interval (seconds)",
    )
    parser.add_argument(
        "--clock-full-every",
        "--clock-full-every-ticks",
        dest="clock_full_every",
        type=int,
        default=CLOCK_DAEMON_FULL_EVERY,
        help="Clock daemon force full refresh every N display ticks (not minutes)",
    )
    parser.add_argument(
        "--clock-data-every-min",
        type=int,
        default=CLOCK_DAEMON_DATA_EVERY_MIN,
        help="Clock daemon refresh non-clock data every N minutes",
    )
    args = parser.parse_args()

    require_ha_credentials = (not args.demo) and args.mode in ("full", "clock-daemon")
    config_required = require_ha_credentials
    config = _load_json("config.json", required=config_required)
    secrets = _load_json("secrets.json", required=require_ha_credentials)
    configure_runtime(config, secrets, require_secrets=require_ha_credentials)

    if "--clock-interval-sec" not in sys.argv:
        args.clock_interval_sec = CLOCK_DAEMON_INTERVAL_SEC
    if "--clock-full-every" not in sys.argv and "--clock-full-every-ticks" not in sys.argv:
        args.clock_full_every = CLOCK_DAEMON_FULL_EVERY
    if "--clock-data-every-min" not in sys.argv:
        args.clock_data_every_min = CLOCK_DAEMON_DATA_EVERY_MIN

    ICON_ASSETS = IconAssets(args.icons_dir)
    args.clock_interval_sec = max(1, int(args.clock_interval_sec))
    args.clock_full_every = max(1, int(args.clock_full_every))
    args.clock_data_every_min = max(1, int(args.clock_data_every_min))

    if args.mode == "clock-daemon":
        run_clock_daemon(
            epd_lib_path=args.epd_lib_path,
            cache_image=args.cache_image,
            interval_sec=args.clock_interval_sec,
            full_every=args.clock_full_every,
            data_every_min=args.clock_data_every_min,
            partial_refresh=args.clock_partial_refresh or bool(CLOCK_PARTIAL_REFRESH),
            partial_fullscreen=bool(CLOCK_PARTIAL_FULLSCREEN),
            demo=args.demo,
        )
        return

    if args.mode == "clock":
        log.info("Clock-only mode: reusing cached full image")
        img = load_cached_full_image(args.cache_image)
        update_clock_header(img)
    else:
        if args.demo:
            log.info("Using demo data")
            data = demo_data()
        else:
            log.info("Fetching from Home Assistant...")
            data = fetch_all_data()

        log.info("Rendering...")
        now = datetime.now()
        img = render(data, now=now, last_updated=now)
        try:
            img.save(args.cache_image, "PNG")
        except Exception as e:
            log.warning(f"Failed to update cache image {args.cache_image}: {e}")

    if args.simulate:
        img.save(args.output, "PNG")
        log.info(f"Preview: {args.output}")
    else:
        clock_partial_refresh = args.clock_partial_refresh or bool(CLOCK_PARTIAL_REFRESH)
        send_to_epaper(
            img,
            args.epd_lib_path,
            mode=args.mode,
            clock_partial_refresh=clock_partial_refresh,
        )
        log.info("Done!")

if __name__ == "__main__":
    main()
