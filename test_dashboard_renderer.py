import unittest

from PIL import Image, ImageDraw, ImageFont

from dashboard_renderer import _fit_text, _primary_alert_text


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


if __name__ == "__main__":
    unittest.main()
