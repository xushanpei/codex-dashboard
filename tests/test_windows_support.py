import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collector
from install_windows import install
from windows_tray import quota_remaining, quota_summary, quota_windows


class WindowsSupportTests(unittest.TestCase):
    def test_store_app_log_location_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp)
            store_logs = local / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Codex/Logs"
            store_logs.mkdir(parents=True)
            self.assertEqual(collector.default_desktop_log_root("nt", local), store_logs)

    def test_windows_install_is_repeatable_and_rewrites_mcp_path(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            source = Path(__file__).resolve().parents[1]
            marketplace = home / ".agents/plugins/marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({"name": "personal", "interface": {"displayName": "Mine"},
                                               "plugins": [{"name": "another-plugin"}]}))
            installed = install(source, home, run_commands=False)
            install(source, home, run_commands=False)
            data = json.loads(marketplace.read_text())
            self.assertEqual(data["interface"]["displayName"], "Mine")
            self.assertEqual([p["name"] for p in data["plugins"]], ["another-plugin", "codex-pulse"])
            mcp = json.loads((installed / ".mcp.json").read_text())["mcpServers"]["codex-pulse"]
            self.assertEqual(mcp["command"], str(installed / ".venv/Scripts/python.exe"))
            self.assertEqual(mcp["args"], [str(installed / "scripts/mcp_server.py")])
            portable = json.loads((installed / "mcp.json").read_text())["mcpServers"]["codex-pulse"]
            self.assertEqual(portable["command"], "py")
            self.assertEqual(portable["args"], ["-3", "${PLUGIN_ROOT}/scripts/mcp_server.py"])
            self.assertTrue((installed / "scripts/windows_tray.py").exists())
            self.assertTrue((installed / "scripts/updater.py").exists())
            self.assertFalse((installed / "dist").exists())

    def test_stale_account_never_shows_old_quota(self):
        account = {"rate_limits": {"primary": {"usedPercent": 26}}, "stale": False}
        self.assertEqual(quota_remaining(account), 74)
        account["stale"] = True
        self.assertIsNone(quota_remaining(account))

    def test_multiple_quota_windows_and_reset_cards(self):
        account = {"auth_type": "chatgpt", "stale": False,
                   "rate_limits_by_limit_id": {"codex": {
                       "primary": {"usedPercent": 20, "windowDurationMins": 300, "resetsAt": 1900000000},
                       "secondary": {"usedPercent": 90, "windowDurationMins": 10080, "resetsAt": 1900100000}}},
                   "rate_limit_reset_credits": {"availableCount": 3}}
        self.assertEqual([row[0] for row in quota_windows(account, "zh")], ["5 小时额度", "1 周额度"])
        self.assertEqual([row[0] for row in quota_windows(account)], ["5-hour quota", "1-week quota"])
        self.assertEqual(quota_remaining(account), 80)
        summary = quota_summary(account, "zh")
        self.assertIn("5 小时额度  剩余 80%", summary)
        self.assertIn("1 周额度  剩余 10%", summary)
        self.assertIn("可用 3 张", summary)

    def test_api_key_account_has_no_chatgpt_quota(self):
        account = {"auth_type": "apiKey", "stale": False,
                   "rate_limits": {"primary": {"usedPercent": 20}}}
        self.assertEqual(quota_windows(account), [])
        self.assertIsNone(quota_remaining(account))
        self.assertIn("Billed by OpenAI API usage", quota_summary(account))


if __name__ == "__main__":
    unittest.main()
