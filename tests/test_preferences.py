import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preferences import read_preferences, save_preferences


class PreferencesTests(unittest.TestCase):
    def test_defaults_and_saved_options(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "preferences.json"
            initial = read_preferences(path)
            self.assertEqual((initial["language"], initial["theme"], initial["show_advanced"]),
                             ("en", "system", False))
            saved = save_preferences({"language": "zh", "theme": "light", "show_trend": False,
                                      "show_advanced": True, "unknown": "ignored"}, path)
            self.assertEqual(saved["language"], "zh")
            self.assertFalse(read_preferences(path)["show_trend"])
            self.assertTrue(read_preferences(path)["show_advanced"])
            self.assertNotIn("unknown", json.loads(path.read_text()))
            self.assertEqual(save_preferences({"language": "invalid"}, path)["language"], "en")


if __name__ == "__main__":
    unittest.main()
