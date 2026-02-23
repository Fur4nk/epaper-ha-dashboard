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
import logging
import argparse
import requests
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CONFIG — loaded from external files                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_json(filename: str) -> dict:
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Copy {filename}.example to {filename} and edit it.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)

_secrets = _load_json("secrets.json")
_config  = _load_json("config.json")

HA_URL         = _secrets["ha_url"]
HA_TOKEN       = _secrets["ha_token"]
ROOMS          = _config["rooms"]
WEATHER_ENTITY = _config["weather_entity"]
OUTDOOR_TEMP   = _config.get("outdoor_temp", "")
OUTDOOR_HUM    = _config.get("outdoor_hum", "")
FOOTER_DAILY_QUOTE = _config.get("footer_daily_quote", True)
FOOTER_QUOTE = _config.get("footer_quote", "")
FOOTER_SOURCE = _config.get("footer_source", "")
QUOTE_API_URL = _config.get("quote_api_url", "https://zenquotes.io/api/today")
QUOTE_CACHE_FILE = _config.get("quote_cache_file", "/tmp/epaper_daily_quote.json")
HEADER_WEEKDAY_FORMAT = _config.get("header_weekday_format", "full")
HEADER_MONTH_FORMAT = _config.get("header_month_format", "full")
FORECAST_WEEKDAY_FORMAT = _config.get("forecast_weekday_format", "abbr")

EPD_MODULE = "epd7in5_V2"
W, H = 480, 800
HEADER_H = 56
# Portrait area that contains the clock text (top-right in UI coordinates).
CLOCK_RECT_PORTRAIT = (300, 0, W, HEADER_H)

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
DEFAULT_ICON_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")
ICON_ASSETS = None

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
            "title":       ImageFont.truetype(bold, 26),
            "time":        ImageFont.truetype(mono, 26),
            "date":        ImageFont.truetype(reg, 13),
            "section":     ImageFont.truetype(bold, 12),
            "room_name":   ImageFont.truetype(bold, 16),
            "temp_big":    ImageFont.truetype(mono, 32),
            "temp_room":   ImageFont.truetype(mono, 24),
            "hum_room":    ImageFont.truetype(mono, 16),
            "weather_sub": ImageFont.truetype(reg, 13),
            "fc_day":      ImageFont.truetype(bold, 12),
            "fc_temp":     ImageFont.truetype(mono, 12),
            "tiny":        ImageFont.truetype(reg, 10),
            "col_hdr":     ImageFont.truetype(bold, 10),
        }
    except OSError:
        log.warning("DejaVu fonts not found, using default")
        d = ImageFont.load_default()
        return {k: d for k in ["title","time","date","section","room_name","temp_big",
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

def _ha_headers():
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

def ha_get_state(entity_id: str):
    if not entity_id:
        return None
    try:
        r = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=_ha_headers(), timeout=10)
        r.raise_for_status()
        state = r.json().get("state")
        return None if state in ("unavailable", "unknown", None) else state
    except Exception as e:
        log.warning(f"Failed to fetch {entity_id}: {e}")
        return None

def ha_get_weather() -> dict:
    result = {"condition": "unknown", "temperature": None, "humidity": None,
              "wind_speed": None, "forecast": []}
    if WEATHER_ENTITY:
        try:
            r = requests.post(f"{HA_URL}/api/services/weather/get_forecasts?return_response",
                              headers=_ha_headers(),
                              json={"entity_id": WEATHER_ENTITY, "type": "daily"}, timeout=10)
            if r.ok:
                svc = r.json()
                if isinstance(svc, dict):
                    # New HA response shape:
                    # {"service_response": {"weather.entity_id": {"forecast": [...]}}}
                    service_response = svc.get("service_response")
                    if isinstance(service_response, dict):
                        weather_data = service_response.get(WEATHER_ENTITY)
                        if isinstance(weather_data, dict) and "forecast" in weather_data:
                            result["forecast"] = weather_data["forecast"][:4]
                    # Backward-compatible fallback for alternate response shapes.
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
            r = requests.get(f"{HA_URL}/api/states/{WEATHER_ENTITY}", headers=_ha_headers(), timeout=10)
            r.raise_for_status()
            data = r.json()
            result["condition"] = data.get("state", "unknown")
            attrs = data.get("attributes", {})
            result["temperature"] = attrs.get("temperature")
            result["humidity"] = attrs.get("humidity")
            result["wind_speed"] = attrs.get("wind_speed")
            if not result["forecast"]:
                result["forecast"] = attrs.get("forecast", [])[:4]
        except Exception as e:
            log.warning(f"Failed to fetch weather: {e}")
    else:
        log.warning("weather_entity is empty in config.json")

    out_t = ha_get_state(OUTDOOR_TEMP)
    out_h = ha_get_state(OUTDOOR_HUM)
    if out_t is not None: result["temperature"] = float(out_t)
    if out_h is not None: result["humidity"] = float(out_h)
    return result

def fetch_all_data() -> dict:
    rooms = []
    for room in ROOMS:
        t, h = ha_get_state(room["temp"]), ha_get_state(room["hum"])
        rooms.append({"name": room["name"], "icon": room["icon"],
                      "temp": float(t) if t else None, "hum": float(h) if h else None})
    return {"rooms": rooms, "weather": ha_get_weather()}

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

WEEKDAYS_ABBR = _config.get("weekdays_abbr", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
MONTHS_ABBR = _config.get(
    "months_abbr",
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
)
WEEKDAYS_FULL = _config.get(
    "weekdays_full",
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
)
MONTHS_FULL = _config.get(
    "months_full",
    [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
)
CONDITION_LABELS = {
    "sunny":"Sereno","clear-night":"Sereno","partlycloudy":"Parz. nuvoloso",
    "cloudy":"Nuvoloso","rainy":"Pioggia","pouring":"Pioggia forte",
    "snowy":"Neve","snowy-rainy":"Nevischio","fog":"Nebbia",
    "hail":"Grandine","lightning":"Temporale","lightning-rainy":"Temporale",
    "windy":"Ventoso","windy-variant":"Ventoso","exceptional":"Eccezionale",
}

if not isinstance(WEEKDAYS_ABBR, list) or len(WEEKDAYS_ABBR) != 7:
    log.warning("Invalid weekdays_abbr in config.json, using defaults")
    WEEKDAYS_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
if not isinstance(WEEKDAYS_FULL, list) or len(WEEKDAYS_FULL) != 7:
    log.warning("Invalid weekdays_full in config.json, using defaults")
    WEEKDAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
if not isinstance(MONTHS_ABBR, list) or len(MONTHS_ABBR) != 12:
    log.warning("Invalid months_abbr in config.json, using defaults")
    MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
if not isinstance(MONTHS_FULL, list) or len(MONTHS_FULL) != 12:
    log.warning("Invalid months_full in config.json, using defaults")
    MONTHS_FULL = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]

if HEADER_WEEKDAY_FORMAT not in ("full", "abbr"):
    log.warning("Invalid header_weekday_format in config.json, using 'full'")
    HEADER_WEEKDAY_FORMAT = "full"
if HEADER_MONTH_FORMAT not in ("full", "abbr"):
    log.warning("Invalid header_month_format in config.json, using 'full'")
    HEADER_MONTH_FORMAT = "full"
if FORECAST_WEEKDAY_FORMAT not in ("full", "abbr"):
    log.warning("Invalid forecast_weekday_format in config.json, using 'abbr'")
    FORECAST_WEEKDAY_FORMAT = "abbr"

FALLBACK_QUOTE = (
    "Sembra sempre impossibile finche non viene fatto.",
    "Nelson Mandela",
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


def draw_header(draw: ImageDraw.ImageDraw, fonts: dict, now: datetime):
    draw.rectangle([(0, 0), (W, HEADER_H)], fill=0)
    draw.text((16, 10), "CASA", fill=255, font=fonts["title"])
    draw.text((W-16, 10), now.strftime("%H:%M"), fill=255, font=fonts["time"], anchor="ra")
    weekday_labels = WEEKDAYS_FULL if HEADER_WEEKDAY_FORMAT == "full" else WEEKDAYS_ABBR
    month_labels = MONTHS_FULL if HEADER_MONTH_FORMAT == "full" else MONTHS_ABBR
    day_name = weekday_labels[now.weekday()]
    month_name = month_labels[now.month - 1]
    draw.text((16, 38), f"{day_name} {now.day} {month_name} {now.year}",
              fill=255, font=fonts["date"])


def update_clock_header(img: Image.Image, now: datetime = None):
    now = now or datetime.now()
    draw = ImageDraw.Draw(img)
    fonts = load_fonts()
    draw_header(draw, fonts, now)


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


def draw_footer(draw: ImageDraw.ImageDraw, fonts: dict, now: datetime):
    footer_top = H - 50
    draw.line([(16, footer_top), (W - 16, footer_top)], fill=0, width=1)
    quote_raw, source_raw = footer_text(now)
    quote_font = fonts["weather_sub"]
    source_font = fonts["tiny"]
    max_w = W - 32
    quote_lines = _wrap_text(draw, quote_raw, quote_font, max_w, max_lines=2)
    source = _fit_text(draw, source_raw, source_font, max_w)

    quote_h = sum(_text_size(draw, ln, quote_font)[1] for ln in quote_lines if ln)
    quote_gaps = max(0, len([ln for ln in quote_lines if ln]) - 1) * 2
    source_h = _text_size(draw, source, source_font)[1] if source else 0
    y = H - (quote_h + quote_gaps + source_h + 8)

    for ln in quote_lines:
        if not ln:
            continue
        w, h = _text_size(draw, ln, quote_font)
        draw.text(((W - w) // 2, y), ln, fill=0, font=quote_font)
        y += h + 2
    if source:
        w, _ = _text_size(draw, source, source_font)
        draw.text(((W - w) // 2, y + 2), source, fill=0, font=source_font)


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


def render(data: dict, now: datetime = None) -> Image.Image:
    img = Image.new("1", (W, H), 255)
    draw = ImageDraw.Draw(img)
    fonts = load_fonts()
    now = now or datetime.now()

    # ── HEADER (dark band) ──────────────────────────────────
    draw_header(draw, fonts, now)
    y = HEADER_H

    # ── OUTDOOR WEATHER ─────────────────────────────────────
    y += 10
    weather = data["weather"]
    cond = weather.get("condition", "unknown")
    out_temp = weather.get("temperature")
    out_hum = weather.get("humidity")
    wind = weather.get("wind_speed")

    draw.text((16, y), "ESTERNO", fill=0, font=fonts["section"])
    y += 18

    # Large weather icon
    icon_cx, icon_cy = 56, y + 28
    icon_ok = ICON_ASSETS.draw_weather(img, cond, icon_cx, icon_cy, 56) if ICON_ASSETS else False
    if not icon_ok:
        Icons.weather(draw, icon_cx, icon_cy, cond, r=26)
    cond_text = CONDITION_LABELS.get(cond, cond.replace("_", " ").title())
    draw.text((icon_cx, icon_cy+34), cond_text, fill=0, font=fonts["tiny"], anchor="mt")

    # Big temperature
    tx = 120
    if out_temp is not None:
        draw.text((tx, y), f"{out_temp:.1f}°", fill=0, font=fonts["temp_big"])
    else:
        draw.text((tx, y), "—.—°", fill=0, font=fonts["temp_big"])

    # Sub info
    parts = []
    if out_hum is not None: parts.append(f"Umidità {out_hum:.0f}%")
    if wind is not None:    parts.append(f"Vento {wind:.0f} km/h")
    draw.text((tx, y+36), "  ·  ".join(parts), fill=0, font=fonts["weather_sub"])
    y += 70

    # ── FORECAST ────────────────────────────────────────────
    forecast = weather.get("forecast", [])
    if forecast:
        y += 2
        draw.line([(16, y), (W-16, y)], fill=0, width=1)
        y += 10
        n_fc = min(len(forecast), 4)
        fc_w = (W - 32) // n_fc
        for i, fc in enumerate(forecast[:n_fc]):
            fx = 16 + i*fc_w + fc_w//2
            try:
                dt_str = fc["datetime"]
                fc_date = datetime.fromisoformat(dt_str.replace("Z","+00:00")) if "T" in dt_str \
                          else datetime.strptime(dt_str[:10], "%Y-%m-%d")
                forecast_weekdays = WEEKDAYS_FULL if FORECAST_WEEKDAY_FORMAT == "full" else WEEKDAYS_ABBR
                dl = forecast_weekdays[fc_date.weekday()]
            except Exception:
                dl = f"+{i+1}"
            draw.text((fx, y), dl, fill=0, font=fonts["fc_day"], anchor="mt")
            fc_cond = fc.get("condition", "unknown")
            fc_icon_ok = ICON_ASSETS.draw_weather(img, fc_cond, fx, y + 26, 28) if ICON_ASSETS else False
            if not fc_icon_ok:
                Icons.weather(draw, fx, y + 26, fc_cond, r=14)
            t_hi = fc.get("temperature","—")
            t_lo = fc.get("templow","—")
            draw.text((fx, y+44), f"{t_hi}°/{t_lo}°", fill=0, font=fonts["fc_temp"], anchor="mt")
        y += 60

    # ── THICK SEPARATOR ─────────────────────────────────────
    y += 4
    draw.rectangle([(0, y), (W, y+2)], fill=0)
    y += 10

    # ── ROOMS HEADER ────────────────────────────────────────
    draw.text((16, y), "STANZE", fill=0, font=fonts["section"])
    col_t = W - 130
    col_h = W - 48
    draw.text((col_t+20, y+1), "TEMP", fill=0, font=fonts["col_hdr"], anchor="mt")
    draw.text((col_h, y+1), "UMID", fill=0, font=fonts["col_hdr"], anchor="mt")
    y += 16
    draw.line([(16, y), (W-16, y)], fill=0, width=1)
    y += 4

    # ── ROOM ROWS ───────────────────────────────────────────
    rooms = data["rooms"]
    available = H - y - 30
    row_h = min(available // len(rooms), 62)

    for i, room in enumerate(rooms):
        ry = y + i * row_h
        ry_mid = ry + row_h // 2

        if i % 2 == 0:
            draw.rectangle([(0, ry), (W, ry+row_h-1)], fill=248)

        room_icon_ok = ICON_ASSETS.draw_room(img, room["icon"], 30, ry_mid, 24) if ICON_ASSETS else False
        if not room_icon_ok:
            Icons.room(draw, 30, ry_mid, room["icon"], s=11)
        draw.text((54, ry_mid), room["name"], fill=0, font=fonts["room_name"], anchor="lm")

        if room["temp"] is not None:
            draw.text((col_t+20, ry_mid), f"{room['temp']:.1f}°", fill=0,
                      font=fonts["temp_room"], anchor="mm")
        else:
            draw.text((col_t+20, ry_mid), "—.—°", fill=0, font=fonts["temp_room"], anchor="mm")

        if room["hum"] is not None:
            draw.text((col_h, ry_mid), f"{room['hum']:.0f}%", fill=0,
                      font=fonts["hum_room"], anchor="mm")
        else:
            draw.text((col_h, ry_mid), "—%", fill=0, font=fonts["hum_room"], anchor="mm")

        # Status indicator
        sx = W - 14
        t, h = room["temp"], room["hum"]
        if t is not None and h is not None:
            if h > 65:
                draw.ellipse([sx-5, ry_mid-5, sx+5, ry_mid+5], fill=0)
            elif t > 24 or t < 18:
                draw.ellipse([sx-5, ry_mid-5, sx+5, ry_mid+5], outline=0, width=2)
                draw.ellipse([sx-2, ry_mid-2, sx+2, ry_mid+2], fill=0)
            else:
                draw.ellipse([sx-5, ry_mid-5, sx+5, ry_mid+5], outline=0, width=1)

        draw.line([(16, ry+row_h-1), (W-16, ry+row_h-1)], fill=200, width=1)

    y = y + len(rooms) * row_h
    draw_footer(draw, fonts, now)

    return img

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  E-PAPER OUTPUT                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _resolve_epd_lib_path(custom_path: str = ""):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.environ.get("EPD_LIB_PATH", "")
    candidate_paths = [
        custom_path,
        env_path,
        os.path.expanduser("~/e-Paper/RaspberryPi_JetsonNano/python/lib"),
        os.path.expanduser("~/src/e-Paper/RaspberryPi_JetsonNano/python/lib"),
        os.path.abspath(os.path.join(script_dir, "..", "e-Paper", "RaspberryPi_JetsonNano", "python", "lib")),
    ]
    normalized = []
    seen = set()
    for p in candidate_paths:
        if not p:
            continue
        ap = os.path.abspath(os.path.expanduser(p))
        if ap not in seen:
            normalized.append(ap)
            seen.add(ap)
    epd_path = next((p for p in normalized if os.path.isdir(p)), None)
    return epd_path, normalized


def _first_callable(obj, names):
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn, name
    return None, None


def _portrait_rect_to_hw(rect):
    x0, y0, x1, y1 = rect
    # PIL rotate(90, expand=True): (x, y) -> (y, W - 1 - x)
    hx0 = int(y0)
    hx1 = int(y1)
    hy0 = int(W - x1)
    hy1 = int(W - x0)
    return hx0, hy0, hx1, hy1


def _align_rect_for_epd(rect, width, height):
    x0, y0, x1, y1 = rect
    x0 = max(0, min(width - 1, x0))
    y0 = max(0, min(height - 1, y0))
    x1 = max(1, min(width, x1))
    y1 = max(1, min(height, y1))
    # Many EPD drivers need x aligned to 8-pixel boundaries.
    x0 = (x0 // 8) * 8
    x1 = min(width, ((x1 + 7) // 8) * 8)
    if x1 <= x0:
        x1 = min(width, x0 + 8)
    if y1 <= y0:
        y1 = min(height, y0 + 1)
    return x0, y0, x1, y1


def _safe_partial_refresh(epd, disp_fn, buffer, rect=None):
    width = int(getattr(epd, "width", 800))
    height = int(getattr(epd, "height", 480))
    if rect is None:
        rect = (0, 0, width, height)
    x0, y0, x1, y1 = _align_rect_for_epd(rect, width, height)
    attempts = [
        lambda: disp_fn(buffer, x0, y0, x1, y1),
        lambda: disp_fn(buffer, x0, y0, x1 - 1, y1 - 1),
        lambda: disp_fn(buffer),
    ]
    for attempt in attempts:
        try:
            attempt()
            return True
        except TypeError:
            continue
    return False


def send_to_epaper(img: Image.Image, epd_lib_path: str = "", mode: str = "full"):
    epd_path, checked_paths = _resolve_epd_lib_path(epd_lib_path)
    if epd_path and epd_path not in sys.path:
        sys.path.insert(0, epd_path)
    try:
        from waveshare_epd import epd7in5_V2 as epd_driver
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "waveshare_epd not found. Checked paths: "
            + ", ".join(checked_paths)
            + ". Set EPD_LIB_PATH or use --epd-lib-path."
        ) from e

    log.info(f"Using Waveshare library path: {epd_path}")
    log.info("Initializing e-Paper...")
    epd = epd_driver.EPD()
    img_hw = img.rotate(90, expand=True)
    buffer = epd.getbuffer(img_hw)

    if mode == "clock":
        init_fn, init_name = _first_callable(epd, ["init_fast", "init_Fast", "init"])
        disp_fn, disp_name = _first_callable(epd, ["displayPartial", "display_partial", "display_Partial"])
        if init_fn and disp_fn:
            init_fn()
            log.info(f"Clock refresh using partial mode ({init_name} + {disp_name})")
            clock_rect_hw = _portrait_rect_to_hw(CLOCK_RECT_PORTRAIT)
            if not _safe_partial_refresh(epd, disp_fn, buffer, rect=clock_rect_hw):
                log.warning("Partial signature mismatch, using full refresh for clock mode")
                epd.init()
                epd.display(buffer)
        else:
            log.warning("Partial refresh not supported by this driver, using full refresh for clock mode")
            epd.init()
            epd.display(buffer)
    else:
        epd.init()
        log.info("Refreshing display...")
        epd.display(buffer)
    log.info("Sleep mode")
    epd.sleep()

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAIN                                                                    ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def main():
    global ICON_ASSETS
    parser = argparse.ArgumentParser(description="HA e-Paper Dashboard")
    parser.add_argument("--simulate", action="store_true", help="Save PNG instead of driving e-paper")
    parser.add_argument("--demo", action="store_true", help="Use demo data instead of fetching from HA")
    parser.add_argument("--output", default="/tmp/epaper_dashboard.png", help="PNG output path")
    parser.add_argument("--mode", choices=["full", "clock"], default="full", help="full: all data, clock: header only")
    parser.add_argument("--epd-lib-path", default="", help="Path to Waveshare python lib dir")
    parser.add_argument("--icons-dir", default="", help="Path to icon assets directory")
    parser.add_argument("--cache-image", default="/tmp/epaper_dashboard_full.png",
                        help="Cached full image used by clock mode")
    args = parser.parse_args()
    ICON_ASSETS = IconAssets(args.icons_dir)

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
        img = render(data)
        try:
            img.save(args.cache_image, "PNG")
        except Exception as e:
            log.warning(f"Failed to update cache image {args.cache_image}: {e}")

    if args.simulate:
        img.save(args.output, "PNG")
        log.info(f"Preview: {args.output}")
    else:
        send_to_epaper(img, args.epd_lib_path, mode=args.mode)
        log.info("Done!")

if __name__ == "__main__":
    main()
