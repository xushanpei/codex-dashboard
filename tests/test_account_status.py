import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import account_status


class AccountStatusTests(unittest.TestCase):
    def test_switch_during_quota_request_retries_new_account(self):
        with tempfile.TemporaryDirectory() as temp:
            old_cache, old_auth = account_status.CACHE, account_status.AUTH
            try:
                account_status.CACHE = Path(temp) / "account.json"
                account_status.AUTH = Path(temp) / "auth.json"
                account_status.CACHE.write_text(json.dumps({"email": "old@example.test", "stale": False}))
                account_status.AUTH.write_text("old login")
                now = time.time_ns()
                os.utime(account_status.CACHE, ns=(now - 30_000_000_000, now - 30_000_000_000))
                os.utime(account_status.AUTH, ns=(now - 20_000_000_000, now - 20_000_000_000))
                calls = 0
                def switched_query():
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        os.utime(account_status.AUTH, ns=(now, now))
                        return {"email": "old@example.test", "rate_limits": {"primary": {"usedPercent": 95}}}
                    return {"email": "new@example.test", "rate_limits": {"primary": {"usedPercent": 4}}}
                with patch.object(account_status, "_query", side_effect=switched_query):
                    result = account_status.read_account()
                self.assertEqual(calls, 2)
                self.assertEqual(result["email"], "new@example.test")
                self.assertEqual(result["rate_limits"]["primary"]["usedPercent"], 4)
            finally:
                account_status.CACHE, account_status.AUTH = old_cache, old_auth

    def test_mismatched_account_and_quota_are_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            old_cache, old_auth = account_status.CACHE, account_status.AUTH
            try:
                account_status.CACHE = Path(temp) / "account.json"
                account_status.AUTH = Path(temp) / "auth.json"
                fresh = {"email": "new@example.test", "rate_limits": {"primary": {"usedPercent": 4}}}
                with patch.object(account_status, "_query", side_effect=[account_status.AccountMismatch(), fresh]) as query:
                    self.assertEqual(account_status.read_account()["email"], "new@example.test")
                    self.assertEqual(query.call_count, 2)
            finally:
                account_status.CACHE, account_status.AUTH = old_cache, old_auth

    def test_login_change_invalidates_cached_quota(self):
        with tempfile.TemporaryDirectory() as temp:
            old_cache, old_auth = account_status.CACHE, account_status.AUTH
            try:
                account_status.CACHE = Path(temp) / "account.json"
                account_status.AUTH = Path(temp) / "auth.json"
                old = {"email": "old@example.test", "plan_type": "team",
                       "rate_limits": {"primary": {"usedPercent": 95}}, "stale": False}
                fresh = {"email": "new@example.test", "plan_type": "team",
                         "rate_limits": {"primary": {"usedPercent": 4}}, "stale": False}
                account_status.CACHE.write_text(json.dumps(old))
                account_status.AUTH.write_text("login changed")
                now = time.time_ns()
                os.utime(account_status.CACHE, ns=(now - 2_000_000_000, now - 2_000_000_000))
                os.utime(account_status.AUTH, ns=(now - 1_000_000_000, now - 1_000_000_000))

                with patch.object(account_status, "_query", return_value=fresh) as query:
                    self.assertEqual(account_status.read_account()["rate_limits"]["primary"]["usedPercent"], 4)
                    query.assert_called_once()
                self.assertEqual(json.loads(account_status.CACHE.read_text())["email"], "new@example.test")

                os.utime(account_status.AUTH, ns=(now + 1_000_000_000, now + 1_000_000_000))
                with patch.object(account_status, "_query", return_value=None):
                    self.assertIsNone(account_status.read_account())
            finally:
                account_status.CACHE, account_status.AUTH = old_cache, old_auth


if __name__ == "__main__":
    unittest.main()
