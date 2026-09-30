import json
import io
import base64
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
    def test_display_name_requires_matching_email_and_account(self):
        claims = {"email": "current@example.test", "name": "  星河  ",
                  "https://api.openai.com/auth": {"chatgpt_account_id": "workspace-current"}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        with tempfile.TemporaryDirectory() as temp:
            old_auth = account_status.AUTH
            try:
                account_status.AUTH = Path(temp) / "auth.json"
                account_status.AUTH.write_text(json.dumps({"tokens": {"id_token": f"header.{payload}.signature"}}))
                account = {"type": "chatgpt", "email": "current@example.test"}
                routing = {"chatgptAccountId": "workspace-current"}
                self.assertEqual(account_status._verified_account_name(account, routing), "星河")
                self.assertIsNone(account_status._verified_account_name(account, {"chatgptAccountId": "other"}))
                self.assertIsNone(account_status._verified_account_name({**account, "email": "other@example.test"}, routing))
                self.assertIsNone(account_status._verified_account_name({**account, "type": "apiKey"}, routing))
            finally:
                account_status.AUTH = old_auth

    def test_old_cache_without_name_is_refreshed_after_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            old_cache, old_auth = account_status.CACHE, account_status.AUTH
            try:
                account_status.CACHE = Path(temp) / "account.json"
                account_status.AUTH = Path(temp) / "auth.json"
                account_status.AUTH.write_text("auth")
                account_status.CACHE.write_text(json.dumps({"auth_type": "chatgpt", "email": "old@example.test"}))
                fresh = {"auth_type": "chatgpt", "email": "new@example.test", "display_name": "New"}
                with patch.object(account_status, "_query", return_value=fresh) as query:
                    self.assertEqual(account_status.read_account()["display_name"], "New")
                    query.assert_called_once()
            finally:
                account_status.CACHE, account_status.AUTH = old_cache, old_auth

    def test_full_chatgpt_limits_and_reset_credits_are_kept(self):
        result = account_status._account_payload(
            {"account": {"type": "chatgpt", "planType": "team"}},
            {"rateLimits": {"primary": {"usedPercent": 92}},
             "rateLimitsByLimitId": {"codex": {"primary": {"windowDurationMins": 300, "usedPercent": 35},
                                                "secondary": {"windowDurationMins": 10080, "usedPercent": 92}}},
             "rateLimitResetCredits": {"availableCount": 3, "credits": [{"title": "Rate-limit reset"}]}})
        self.assertEqual(result["rate_limits_by_limit_id"]["codex"]["secondary"]["windowDurationMins"], 10080)
        self.assertEqual(result["rate_limit_reset_credits"]["availableCount"], 3)

    def test_api_key_account_survives_missing_chatgpt_rate_limits(self):
        class FakeProcess:
            stdin = io.BytesIO()
            stdout = [json.dumps({"id": 2, "result": {"account": {"type": "apiKey"}}}).encode() + b"\n",
                      json.dumps({"id": 3, "error": {"code": -32000, "message": "not available"}}).encode() + b"\n"]

            def terminate(self): pass
            def wait(self, timeout=None): return 0

        with patch.object(account_status, "_codex_binary", return_value="codex"), \
             patch.object(account_status.subprocess, "Popen", return_value=FakeProcess()):
            result = account_status._query()
        self.assertEqual(result["auth_type"], "apiKey")
        self.assertIsNone(result["rate_limits"])
        self.assertEqual(result["rate_limits_by_limit_id"], {})

    def test_api_key_switch_discards_chatgpt_limits_from_overlapping_response(self):
        result = account_status._account_payload(
            {"account": {"type": "apiKey"}},
            {"rateLimits": {"primary": {"usedPercent": 91}},
             "rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 91}}},
             "rateLimitResetCredits": {"availableCount": 3}})
        self.assertIsNone(result["rate_limits"])
        self.assertEqual(result["rate_limits_by_limit_id"], {})
        self.assertIsNone(result["rate_limit_reset_credits"])

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
