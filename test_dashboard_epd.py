import unittest

from dashboard_epd import apply_gray_fix


class RecordingEpd:
    def __init__(self):
        self.calls = []

    def send_command(self, value):
        self.calls.append(("command", value))

    def send_data(self, value):
        self.calls.append(("data", value))


class ApplyGrayFixTests(unittest.TestCase):
    def test_sends_waveshare_gray_screen_register_sequence(self):
        epd = RecordingEpd()

        self.assertTrue(apply_gray_fix(epd))

        self.assertEqual(
            epd.calls,
            [
                ("command", 0x50),
                ("data", 0x10),
                ("data", 0x17),
                ("command", 0x52),
                ("data", 0x03),
            ],
        )

    def test_returns_false_when_driver_does_not_expose_low_level_commands(self):
        self.assertFalse(apply_gray_fix(object()))


if __name__ == "__main__":
    unittest.main()
