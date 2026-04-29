import unittest
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from dashboard_renderer import _fit_text, _format_temp_range, _primary_alert_text
from ha_epaper_dashboard import IconAssets, W, H, build_settings, demo_data, render


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


class DemoRenderTests(unittest.TestCase):
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
