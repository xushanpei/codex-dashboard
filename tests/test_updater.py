import hashlib
import io
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import updater


class FakeOpener:
    def __init__(self, data):
        self.data = data

    def open(self, request, timeout=None):
        return io.BytesIO(self.data)


class UpdaterTests(unittest.TestCase):
    def test_release_check_requires_trusted_asset_and_newer_version(self):
        payload = {"tag_name": "v0.2.0", "html_url": "https://github.com/xushanpei/codex-pulse/releases/tag/v0.2.0",
                   "assets": [{"name": "CodexPulse-macOS-universal.zip", "size": 4,
                               "digest": "sha256:" + "a" * 64,
                               "browser_download_url": "https://github.com/xushanpei/codex-pulse/releases/download/v0.2.0/CodexPulse-macOS-universal.zip"}]}
        opener = FakeOpener(json.dumps(payload).encode())
        self.assertTrue(updater.check_update("0.1.9", "darwin", opener)["available"])
        self.assertFalse(updater.check_update("0.2.0", "darwin", opener)["available"])
        payload["assets"][0]["browser_download_url"] = "https://example.com/update.zip"
        with self.assertRaises(updater.UpdateError):
            updater.latest_release("darwin", FakeOpener(json.dumps(payload).encode()))

    def test_download_checks_digest_and_archive_paths(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("Codex Pulse.app/Contents/Info.plist", "ok")
        data = stream.getvalue()
        release = {"asset_url": "https://github.com/example.zip", "size": len(data),
                   "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "update.zip"
            updater.download_asset(release, path, FakeOpener(data))
            self.assertEqual(path.read_bytes(), data)
            with self.assertRaises(updater.UpdateError):
                updater.download_asset({**release, "digest": "sha256:" + "0" * 64}, path, FakeOpener(data))
            bad = io.BytesIO()
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("../escape", "bad")
            bad_data = bad.getvalue()
            with self.assertRaises(updater.UpdateError):
                updater.download_asset({**release, "size": len(bad_data),
                                        "digest": "sha256:" + hashlib.sha256(bad_data).hexdigest()},
                                       path, FakeOpener(bad_data))

    def test_macos_app_identity_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / "Codex Pulse.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            (app / "Contents/MacOS/CodexPulse").write_bytes(b"binary")
            info = {"CFBundleIdentifier": "local.codex.pulse", "CFBundleShortVersionString": "0.2.0"}
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
            updater.validate_macos_app(app, "0.2.0")
            with self.assertRaises(updater.UpdateError):
                updater.validate_macos_app(app, "0.2.1")

    @unittest.skipUnless(sys.platform == "darwin", "macOS app replacement uses ditto")
    def test_macos_install_stages_and_keeps_previous_app(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = root / "Codex Pulse.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            (app / "Contents/MacOS/CodexPulse").write_bytes(b"old")
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "local.codex.pulse", "CFBundleShortVersionString": "0.1.2"}))
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as source:
                source.writestr("Codex Pulse.app/Contents/MacOS/CodexPulse", b"new")
                source.writestr("Codex Pulse.app/Contents/Info.plist", plistlib.dumps({
                    "CFBundleIdentifier": "local.codex.pulse", "CFBundleShortVersionString": "0.1.3"}))
            real_run = subprocess.run

            def run(command, *args, **kwargs):
                if command[0] == "open":
                    return subprocess.CompletedProcess(command, 0)
                return real_run(command, *args, **kwargs)

            release = {"available": True, "latest_version": "0.1.3"}
            with patch.object(updater, "check_update", return_value=release), \
                 patch.object(updater, "download_asset", side_effect=lambda _release, path: path.write_bytes(archive.getvalue())), \
                 patch.object(updater, "update_git_plugin", return_value=None), \
                 patch.object(updater, "STATUS", root / "update-status.json"), \
                 patch.object(updater.subprocess, "run", side_effect=run):
                updater.install_macos(app, 0, "0.1.2")
            self.assertEqual((app / "Contents/MacOS/CodexPulse").read_bytes(), b"new")
            self.assertEqual((root / ".Codex Pulse.0.1.2.backup.app/Contents/MacOS/CodexPulse").read_bytes(), b"old")
            self.assertEqual(json.loads((root / "update-status.json").read_text())["state"], "complete")

    @unittest.skipUnless(sys.platform == "win32", "Windows process handle check")
    def test_windows_detects_exited_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"],
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.assertTrue(updater.process_running(process.pid))
        finally:
            process.wait(timeout=5)
        self.assertFalse(updater.process_running(process.pid))


if __name__ == "__main__":
    unittest.main()
