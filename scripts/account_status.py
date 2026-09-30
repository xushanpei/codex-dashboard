"""Read account identity and limits through the documented Codex app-server API."""
from __future__ import annotations

import base64
import binascii
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path.home() / ".codex/codex-pulse/account.json"
AUTH = Path.home() / ".codex/auth.json"
TTL_SECONDS = 15


class AccountMismatch(Exception):
    """Account identity changed while account and quota were being read."""


def _account_payload(account_result, limit_result):
    account = account_result.get("account") or {}
    if not account:
        return None
    legacy = limit_result.get("rateLimits")
    if not isinstance(legacy, dict):
        legacy = None
    by_id = limit_result.get("rateLimitsByLimitId")
    reset_credits = limit_result.get("rateLimitResetCredits")
    buckets = by_id if isinstance(by_id, dict) else {}
    if account.get("type") != "chatgpt":
        legacy, buckets, reset_credits = None, {}, None
    bucket_plan = next((item.get("planType") for item in buckets.values()
                        if isinstance(item, dict) and item.get("planType")), None)
    display_name = _verified_account_name(account, account_result.get("workspaceRouting") or {})
    return {
        "email": account.get("email"),
        "display_name": display_name,
        "plan_type": account.get("planType") or (legacy or {}).get("planType") or bucket_plan,
        "auth_type": account.get("type"),
        "rate_limits": legacy,
        "rate_limits_by_limit_id": buckets,
        "rate_limit_reset_credits": reset_credits if isinstance(reset_credits, dict) else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stale": False,
    }


def _verified_account_name(account, workspace_routing):
    """Use the current local ID token only when it matches the app-server account."""
    if account.get("type") != "chatgpt" or not account.get("email"):
        return None
    try:
        token = (json.loads(AUTH.read_text()).get("tokens") or {}).get("id_token") or ""
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (OSError, ValueError, IndexError, TypeError, binascii.Error):
        return None
    if (claims.get("email") or "").casefold() != account["email"].casefold():
        return None
    routed_id = workspace_routing.get("chatgptAccountId")
    token_id = (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
    if routed_id and token_id != routed_id:
        return None
    name = claims.get("name")
    return name.strip()[:100] if isinstance(name, str) and name.strip() else None


def _auth_version():
    try:
        return AUTH.stat().st_mtime_ns
    except OSError:
        return 0


def _codex_binary():
    candidates = [
        os.environ.get("CODEX_PULSE_CODEX"),
        shutil.which("codex"),
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
        str(Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ]
    return next((path for path in candidates if path and os.access(path, os.X_OK)), None)


def _query():
    codex = _codex_binary()
    if not codex:
        return None
    process = subprocess.Popen([codex, "app-server"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    requests = [
        {"method": "initialize", "id": 1, "params": {"clientInfo": {
            "name": "codex_pulse", "title": "Codex Dashboard", "version": "0.1.0"}}},
        {"method": "initialized", "params": {}},
        {"method": "account/read", "id": 2, "params": {"refreshToken": False}},
        {"method": "account/rateLimits/read", "id": 3},
    ]
    try:
        for request in requests:
            process.stdin.write((json.dumps(request) + "\n").encode())
        process.stdin.flush()
        found = {}
        messages = queue.Queue()
        def read_messages():
            for line in process.stdout:
                messages.put(line)
            messages.put(None)
        threading.Thread(target=read_messages, daemon=True).start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not {2, 3}.issubset(found):
            try:
                line = messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if message.get("id") in (2, 3):
                found[message["id"]] = message.get("result") or {}
        if not found.get(2, {}).get("account"):
            return None
        workspace_id = (found.get(2, {}).get("workspaceRouting") or {}).get("chatgptAccountId")
        quota_account_id = found.get(3, {}).get("accountId")
        if workspace_id and quota_account_id and workspace_id != quota_account_id:
            raise AccountMismatch("Account changed during quota read")
        return _account_payload(found[2], found.get(3, {}))
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def read_account():
    cached = None
    cache_matches_login = False
    try:
        cached = json.loads(CACHE.read_text())
        cache_stat = CACHE.stat()
        auth_changed_at = _auth_version()
        cache_matches_login = cache_stat.st_mtime_ns >= auth_changed_at
        has_name_field = cached.get("auth_type") != "chatgpt" or "display_name" in cached
        if cache_matches_login and has_name_field and time.time() - cache_stat.st_mtime < TTL_SECONDS:
            return cached
    except (OSError, ValueError):
        pass
    auth_before = _auth_version()
    fresh = None
    for _ in range(2):
        try:
            fresh = _query()
            break
        except AccountMismatch:
            continue
        except (OSError, ValueError, subprocess.SubprocessError):
            break
    auth_after = _auth_version()
    if auth_after != auth_before:
        cache_matches_login = False
        try:
            fresh = _query()
        except (AccountMismatch, OSError, ValueError, subprocess.SubprocessError):
            fresh = None
        if _auth_version() != auth_after:
            fresh = None
    if fresh:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temp = CACHE.with_name(f"account-{os.getpid()}.tmp")
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(fresh, stream)
        os.replace(temp, CACHE)
        return fresh
    return {**cached, "stale": True} if cached and cache_matches_login else None
