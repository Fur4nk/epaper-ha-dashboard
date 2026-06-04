import unittest
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from dashboard_renderer import _draw_outdoor_block, _draw_rooms_block, _fit_text, _format_temp_range, _primary_alert_text
from ha_epaper_dashboard import IconAssets, W, H, _outdoor_focus_active, build_settings, demo_data, load_fonts, render


class PrimaryAlertTextTests(unittest.TestCase):
    def test_omits_color_severity_prefix_from_alert_text(self):
        text = _primary_alert_text({"severity": "YELLOW", "event": "Temporali forti"})

        self.assertEqual(text, "Temporali forti")

    def test_omits_case_insensitive_color_severity_prefix_already_in_event(self):
        text = _primary_alert_text({"severity": "yellow", "event": "YELLOW Temporali forti"})

        self.assertEqual(text, "Temporali forti")

    def test_keeps_unknown_severity_prefix_for_context(self):
        text = _primary_alert_text({"severity": "custom", "event": "Temporali forti"})

        self.assertEqual(text, "custom Temporali forti")


class FitTextTests(unittest.TestCase):
    def test_truncated_text_with_ellipsis_fits_max_width(self):
        img = Image.new("1", (200, 40), 255)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        max_width = int(draw.textlength("TE", font=font))

        text = _fit_text(draw, "TEMPORALI FORTI E VENTO", font, max_width)

        self.assertLessEqual(draw.textlength(text, font=font), max_width)
        self.assertTrue(text.endswith("…"))


class FormatTempRangeTests(unittest.TestCase):
    def test_formats_high_before_low(self):
        text = _format_temp_range(18.2, 25.6)

        self.assertEqual(text, "26°/18°")

    def test_uses_placeholder_for_missing_values(self):
        text = _format_temp_range(None, 25.6)

        self.assertEqual(text, "26°/—°")


class OutdoorBlockRenderTests(unittest.TestCase):
    def test_weather_alert_warning_line_is_lowered_in_info_area(self):
        img = Image.new("1", (W, H), 255)
        base_draw = ImageDraw.Draw(img)
        draw = RecordingDraw(base_draw)
        icon_assets = RecordingIconAssets()

        _draw_outdoor_block(
            draw,
            img,
            {
                "condition": "sunny",
                "temperature": 21,
                "humidity": 52,
                "wind_speed": 8,
                "uv_index": 2,
                "alert": {"event": "Temporali forti", "severity": "yellow"},
                "dayparts": {},
            },
            y=56,
            width=W,
            fonts=load_fonts(),
            icon_assets=icon_assets,
            icons_cls=None,
            condition_labels={},
            intraday_labels=[],
            labels={},
        )

        self.assertIn(("weather", "alert", 22, 156, 16), icon_assets.draw_calls)
        self.assertIn(((34, 149), "TEMPORALI FORTI"), draw.text_calls)

    def test_focus_mode_enlarges_outdoor_temperature_and_keeps_today_range(self):
        img = Image.new("1", (W, H), 255)
        base_draw = ImageDraw.Draw(img)
        draw = RecordingDraw(base_draw)
        icon_assets = RecordingIconAssets()

        next_y = _draw_outdoor_block(
            draw,
            img,
            {
                "condition": "cloudy",
                "temperature": 8.2,
                "humidity": 72,
                "wind_speed": 12,
                "alert": {"event": "Wind Warning", "severity": "yellow"},
                "dayparts": {
                    "morning": {"min": 5, "max": 11, "condition": "cloudy"},
                },
            },
            y=56,
            width=W,
            fonts=load_fonts(),
            icon_assets=icon_assets,
            icons_cls=None,
            condition_labels={"cloudy": "Nuvoloso"},
            intraday_labels=["Mattina", "Pomeriggio", "Sera"],
            labels={},
            outdoor_focus=True,
        )

        self.assertGreater(next_y, 168)
        self.assertTrue(any(text == "8" and 50 <= xy[0] <= 90 for xy, text in draw.text_calls))
        self.assertTrue(any(text == "WIND WARNING" and 80 <= xy[0] <= 110 and xy[1] >= 148 for xy, text in draw.text_calls))
        self.assertTrue(any(name == "alert" and cx < 140 for _, name, cx, _, _ in icon_assets.draw_calls))
        self.assertTrue(any(text == "11°/5°" for _, text in draw.text_calls))
        self.assertTrue(any(63 <= size <= 67 for _, _, _, size in icon_assets.weather_draw_calls))
        self.assertTrue(any(text == "Nuvoloso" and xy[0] > 320 and xy[1] <= 160 for xy, text in draw.text_calls))
        self.assertTrue(any(text == "11°/5°" and xy[0] > 320 for xy, text in draw.text_calls))
        self.assertTrue(any(text == "Hu 72%" and xy[0] > 320 for xy, text in draw.text_calls))
        self.assertTrue(any(text == "Wi 12 km/h" and xy[0] > 320 for xy, text in draw.text_calls))


class RoomsBlockRenderTests(unittest.TestCase):
    def test_compact_rooms_use_shorter_rows(self):
        img = Image.new("1", (W, H), 255)
        data = demo_data()
        fonts = load_fonts()
        icon_assets = RecordingIconAssets()

        normal_y = _draw_rooms_block(
            ImageDraw.Draw(img.copy()),
            img.copy(),
            data,
            y=310,
            width=W,
            height=H,
            fonts=fonts,
            icon_assets=icon_assets,
            icons_cls=None,
            labels={},
            room_temp_min=18,
            room_temp_max=24,
            room_humidity_max=65,
        )
        compact_y = _draw_rooms_block(
            ImageDraw.Draw(img.copy()),
            img.copy(),
            data,
            y=360,
            width=W,
            height=H,
            fonts=fonts,
            icon_assets=icon_assets,
            icons_cls=None,
            labels={},
            room_temp_min=18,
            room_temp_max=24,
            room_humidity_max=65,
            rooms_compact=True,
        )

        self.assertLess(compact_y - 360, normal_y - 310)


class RecordingDraw:
    def __init__(self, draw):
        self.draw = draw
        self.text_calls = []

    def text(self, xy, text, *args, **kwargs):
        self.text_calls.append((xy, text))
        return self.draw.text(xy, text, *args, **kwargs)

    def textlength(self, text, *args, **kwargs):
        return self.draw.textlength(text, *args, **kwargs)

    def line(self, *args, **kwargs):
        return self.draw.line(*args, **kwargs)

    def polygon(self, *args, **kwargs):
        return self.draw.polygon(*args, **kwargs)


class RecordingIconAssets:
    def __init__(self):
        self.draw_calls = []
        self.weather_draw_calls = []

    def draw(self, img, category, name, cx, cy, size):
        self.draw_calls.append((category, name, cx, cy, size))
        return True

    def draw_weather(self, img, condition, cx, cy, size):
        self.weather_draw_calls.append((condition, cx, cy, size))
        return True

    def draw_room(self, img, name, cx, cy, size):
        return True


class DemoRenderTests(unittest.TestCase):
    def test_forecast_fonts_are_large_enough_for_epaper_readability(self):
        import ha_epaper_dashboard

        fonts = ha_epaper_dashboard.load_fonts()

        self.assertGreaterEqual(fonts["fc_day"].size, 16)
        self.assertGreaterEqual(fonts["fc_temp"].size, 16)
        self.assertIn("Bold", fonts["fc_day"].getname()[1])

    def test_demo_intraday_data_exercises_min_max_rendering(self):
        data = demo_data()

        for key in ("morning", "afternoon", "evening"):
            self.assertIn("min", data["weather"]["dayparts"][key])
            self.assertIn("max", data["weather"]["dayparts"][key])

    def test_demo_dashboard_renders_nonblank_preview_without_network_quote(self):
        data = demo_data()
        settings = build_settings(
            {
                "footer_daily_quote": False,
                "footer_quote": "Render smoke test",
                "footer_source": "unittest",
            },
            {},
            require_secrets=False,
        )

        img = render(data, settings, IconAssets("/missing-icons"), now=datetime(2026, 4, 29, 9, 30), last_updated=datetime(2026, 4, 29, 9, 30))

        self.assertEqual(img.size, (W, H))
        self.assertEqual(img.mode, "1")
        self.assertIsNotNone(img.getbbox(), "Rendered dashboard preview should not be blank")


class SettingsTests(unittest.TestCase):
    def test_build_settings_defaults_to_conservative_data_refresh(self):
        settings = build_settings({}, {}, require_secrets=False)

        self.assertFalse(settings.clock_partial_fullscreen)
        self.assertTrue(settings.epd_sleep_after_refresh)

    def test_build_settings_defaults_morning_focus_window(self):
        settings = build_settings({}, {}, require_secrets=False)

        self.assertTrue(settings.outdoor_focus_enabled)
        self.assertEqual(settings.outdoor_focus_start, "07:00")
        self.assertEqual(settings.outdoor_focus_end, "08:30")

    def test_build_settings_parses_morning_focus_window(self):
        settings = build_settings(
            {
                "outdoor_focus_enabled": False,
                "outdoor_focus_start": "06:45",
                "outdoor_focus_end": "09:15",
            },
            {},
            require_secrets=False,
        )

        self.assertFalse(settings.outdoor_focus_enabled)
        self.assertEqual(settings.outdoor_focus_start, "06:45")
        self.assertEqual(settings.outdoor_focus_end, "09:15")

    def test_outdoor_focus_active_only_inside_configured_window(self):
        settings = build_settings({}, {}, require_secrets=False)

        self.assertFalse(_outdoor_focus_active(settings, datetime(2026, 4, 30, 6, 59)))
        self.assertTrue(_outdoor_focus_active(settings, datetime(2026, 4, 30, 7, 0)))
        self.assertTrue(_outdoor_focus_active(settings, datetime(2026, 4, 30, 8, 29)))
        self.assertFalse(_outdoor_focus_active(settings, datetime(2026, 4, 30, 8, 30)))

    def test_build_settings_parses_room_comfort_thresholds(self):
        settings = build_settings(
            {
                "room_temp_min": 19,
                "room_temp_max": 25.5,
                "room_humidity_max": 60,
            },
            {},
            require_secrets=False,
        )

        self.assertEqual(settings.room_temp_min, 19.0)
        self.assertEqual(settings.room_temp_max, 25.5)
        self.assertEqual(settings.room_humidity_max, 60.0)


if __name__ == "__main__":
    unittest.main()
