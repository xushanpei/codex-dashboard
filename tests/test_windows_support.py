import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collector
from install_windows import install
from windows_tray import quota_remaining


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
            self.assertFalse((installed / "dist").exists())

    def test_stale_account_never_shows_old_quota(self):
        account = {"rate_limits": {"primary": {"usedPercent": 26}}, "stale": False}
        self.assertEqual(quota_remaining(account), 74)
        account["stale"] = True
        self.assertIsNone(quota_remaining(account))


if __name__ == "__main__":
    unittest.main()
