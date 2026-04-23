import unittest

from dashboard_partial import build_dynamic_partial_rects


class BuildDynamicPartialRectsTests(unittest.TestCase):
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
