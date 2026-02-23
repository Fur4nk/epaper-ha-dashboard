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

EPD_MODULE = "epd7in5_V2"
W, H = 480, 800

FONT_DIR = "/usr/share/fonts/truetype/dejavu"

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

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  HOME ASSISTANT API                                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _ha_headers():
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

def ha_get_state(entity_id: str):
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
    try:
        r = requests.post(f"{HA_URL}/api/services/weather/get_forecasts",
                          headers=_ha_headers(),
                          json={"entity_id": WEATHER_ENTITY, "type": "daily"}, timeout=10)
        if r.ok:
            svc = r.json()
            if isinstance(svc, dict):
                for val in svc.values():
                    if isinstance(val, dict) and "forecast" in val:
                        result["forecast"] = val["forecast"][:4]
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

GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
MESI = ["gen","feb","mar","apr","mag","giu","lug","ago","set","ott","nov","dic"]
CONDIZIONI = {
    "sunny":"Sereno","clear-night":"Sereno","partlycloudy":"Parz. nuvoloso",
    "cloudy":"Nuvoloso","rainy":"Pioggia","pouring":"Pioggia forte",
    "snowy":"Neve","snowy-rainy":"Nevischio","fog":"Nebbia",
    "hail":"Grandine","lightning":"Temporale","lightning-rainy":"Temporale",
    "windy":"Ventoso","windy-variant":"Ventoso","exceptional":"Eccezionale",
}

def render(data: dict) -> Image.Image:
    img = Image.new("1", (W, H), 255)
    draw = ImageDraw.Draw(img)
    fonts = load_fonts()
    now = datetime.now()

    # ── HEADER (dark band) ──────────────────────────────────
    draw.rectangle([(0, 0), (W, 56)], fill=0)
    draw.text((16, 10), "CASA", fill=255, font=fonts["title"])
    draw.text((W-16, 10), now.strftime("%H:%M"), fill=255, font=fonts["time"], anchor="ra")
    day_name = GIORNI[now.weekday()]
    draw.text((16, 38), f"{day_name} {now.day} {MESI[now.month-1]} {now.year}",
              fill=255, font=fonts["date"])
    y = 56

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
    Icons.weather(draw, icon_cx, icon_cy, cond, r=26)
    cond_text = CONDIZIONI.get(cond, cond.replace("_"," ").title())
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
                dl = GIORNI[fc_date.weekday()]
            except Exception:
                dl = f"+{i+1}"
            draw.text((fx, y), dl, fill=0, font=fonts["fc_day"], anchor="mt")
            Icons.weather(draw, fx, y+26, fc.get("condition","unknown"), r=14)
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

    return img

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  E-PAPER OUTPUT                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def send_to_epaper(img: Image.Image):
    epd_path = os.path.expanduser("~/e-Paper/RaspberryPi_JetsonNano/python/lib")
    if epd_path not in sys.path:
        sys.path.insert(0, epd_path)
    from waveshare_epd import epd7in5_V2 as epd_driver

    log.info("Initializing e-Paper...")
    epd = epd_driver.EPD()
    epd.init()
    img_hw = img.rotate(90, expand=True)
    log.info("Refreshing display...")
    epd.display(epd.getbuffer(img_hw))
    log.info("Sleep mode")
    epd.sleep()

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAIN                                                                    ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def main():
    parser = argparse.ArgumentParser(description="HA e-Paper Dashboard")
    parser.add_argument("--simulate", action="store_true", help="Save PNG instead of driving e-paper")
    parser.add_argument("--demo", action="store_true", help="Use demo data instead of fetching from HA")
    parser.add_argument("--output", default="/tmp/epaper_dashboard.png", help="PNG output path")
    args = parser.parse_args()

    if args.demo:
        log.info("Using demo data")
        data = demo_data()
    else:
        log.info("Fetching from Home Assistant...")
        data = fetch_all_data()

    log.info("Rendering...")
    img = render(data)

    if args.simulate:
        img.save(args.output, "PNG")
        log.info(f"Preview: {args.output}")
    else:
        send_to_epaper(img)
        log.info("Done!")

if __name__ == "__main__":
    main()
