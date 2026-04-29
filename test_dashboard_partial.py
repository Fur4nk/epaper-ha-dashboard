import unittest

from dashboard_partial import build_data_snapshot, build_dynamic_partial_rects


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


class BuildDynamicPartialRectsTests(unittest.TestCase):
    def test_room_snapshot_status_uses_custom_comfort_thresholds(self):
        data = {
            "weather": {},
            "rooms": [
                {"name": "Studio", "temp": 25.0, "hum": 60, "metrics": []},
            ],
        }

        default_snapshot = build_data_snapshot(data, _to_float)
        custom_snapshot = build_data_snapshot(
            data,
            _to_float,
            room_temp_min=18.0,
            room_temp_max=26.0,
            room_humidity_max=65.0,
        )

        self.assertEqual(default_snapshot["rooms"][0][3], "temp_alert")
        self.assertEqual(custom_snapshot["rooms"][0][3], "ok")

    def test_alert_partial_refresh_covers_outdoor_warning_line(self):
        data = {
            "weather": {
                "alert": {"event": "Temporali forti", "severity": "yellow"},
                "dayparts": {},
            },
            "rooms": [],
        }
        changed = {
            "outdoor": False,
            "intraday": False,
            "forecast": False,
            "alert": True,
            "rooms": set(),
            "footer": False,
        }

        rects = build_dynamic_partial_rects(data, header_h=56, width=480, height=800, changed=changed)

        self.assertIn((12, 74, 190, 162), rects)

    def test_forecast_partial_refresh_covers_temperature_line(self):
        data = {
            "weather": {
                "forecast": [
                    {"datetime": "2026-04-30", "condition": "sunny", "temperature": 24, "templow": 16},
                ],
            },
            "rooms": [],
        }
        changed = {
            "outdoor": False,
            "intraday": False,
            "forecast": True,
            "alert": False,
            "rooms": set(),
            "footer": False,
        }

        rects = build_dynamic_partial_rects(data, header_h=56, width=480, height=800, changed=changed)
        forecast_rect = rects[0]

        self.assertLessEqual(forecast_rect[1], 176, "Forecast partial refresh must cover weekday labels")
        self.assertGreaterEqual(forecast_rect[3], 246, "Forecast partial refresh must cover temperature text")

    def test_room_partial_refresh_covers_full_metrics_area(self):
        data = {
            "weather": {},
            "rooms": [
                {
                    "name": "Soggiorno",
                    "temp": 21.4,
                    "hum": 48,
                    "metrics": [
                        {"key": "temp", "value": 21.4, "decimals": 1},
                        {"key": "hum", "value": 48, "decimals": 0},
                        {"key": "co2", "value": 650, "decimals": 0},
                    ],
                }
            ],
        }
        changed = {
            "outdoor": False,
            "intraday": False,
            "forecast": False,
            "alert": False,
            "rooms": {0},
            "footer": False,
        }

        rects = build_dynamic_partial_rects(data, header_h=56, width=480, height=800, changed=changed)

        self.assertEqual(len(rects), 1)
        room_rect = rects[0]
        self.assertLessEqual(
            room_rect[0],
            300,
            "Room partial refresh must cover the full metrics area, including the first column",
        )

    def test_changed_room_row_starts_at_renderer_metrics_boundary(self):
        data = {
            "weather": {},
            "rooms": [
                {"name": "Cucina", "temp": 20.1, "hum": 50, "metrics": [{"key": "temp", "value": 20.1, "decimals": 1}]},
                {
                    "name": "Soggiorno",
                    "temp": 21.4,
                    "hum": 48,
                    "metrics": [
                        {"key": "temp", "value": 21.4, "decimals": 1},
                        {"key": "hum", "value": 48, "decimals": 0},
                        {"key": "co2", "value": 650, "decimals": 0},
                    ],
                },
                {"name": "Camera", "temp": 19.8, "hum": 53, "metrics": [{"key": "temp", "value": 19.8, "decimals": 1}]},
            ],
        }
        changed = {
            "outdoor": False,
            "intraday": False,
            "forecast": False,
            "alert": False,
            "rooms": {1},
            "footer": False,
        }

        rects = build_dynamic_partial_rects(data, header_h=56, width=480, height=800, changed=changed)

        self.assertEqual(len(rects), 1)
        self.assertEqual(rects[0][0], 300)


if __name__ == "__main__":
    unittest.main()
