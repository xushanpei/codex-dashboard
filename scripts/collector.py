#!/usr/bin/env python3
"""Incrementally summarize local Codex token records; never store prompts."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from account_status import read_account

ROOT = Path(os.environ.get("CODEX_SESSIONS_DIR", str(Path.home() / ".codex/sessions")))


def default_desktop_log_root(platform_name=None, local_app_data=None):
    if (platform_name or os.name) != "nt":
        return Path.home() / "Library/Logs/com.openai.codex"
    local = Path(local_app_data or os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    candidates = list((local / "Packages").glob("OpenAI.Codex_*/LocalCache/Local/Codex/Logs"))
    candidates += [local / "Codex/Logs", local / "OpenAI/Codex/Logs"]
    existing = [path for path in candidates if path.is_dir()]
    return max(existing, key=lambda path: path.stat().st_mtime) if existing else local / "Codex/Logs"


DESKTOP_LOG_ROOT = Path(os.environ.get("CODEX_DESKTOP_LOG_DIR", str(default_desktop_log_root())))
CACHE = Path(os.environ.get("CODEX_PULSE_CACHE", str(Path.home() / ".codex/codex-pulse/usage.sqlite3")))
FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
VIEW_EVENT = re.compile(r"thread_stream_view_activity_changed\s+active=(true|false)\s+conversationId=([0-9a-f-]{36}).*?rendererWindowFocused=(true|false).*?rendererWindowId=(\d+).*?rendererWindowVisible=(true|false)")
ROUTE_EVENT = re.compile(r"IAB_LIFECYCLE received browser sidebar owner sync .*?originWebContentsId=(\d+) ownerRoutePath=/local/([0-9a-f-]{36})\s+windowId=(\d+)")
QUEUE_EVENT = re.compile(r"\[AppServerConnection\] response_routed .*?conversationId=([0-9a-f-]{36}).*?errorCode=null.*?method=thread/queue/list\s+originWebcontentsId=(\d+)")
WEB_CONTENTS = re.compile(r"rendererWebContentsId=(\d+)")
SESSION_ID_IN_NAME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def values(obj):
    return tuple(max(0, int((obj or {}).get(k, 0) or 0)) for k in FIELDS)


def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, inode INTEGER, offset INTEGER, size INTEGER);
    CREATE TABLE IF NOT EXISTS usage(
      response_id TEXT PRIMARY KEY, session_id TEXT, at TEXT,
      input_tokens INTEGER, cached_input_tokens INTEGER, cache_write_input_tokens INTEGER,
      output_tokens INTEGER, reasoning_output_tokens INTEGER, total_tokens INTEGER);
    CREATE TABLE IF NOT EXISTS sessions(
      session_id TEXT PRIMARY KEY, path TEXT, at TEXT,
      input_tokens INTEGER, cached_input_tokens INTEGER, cache_write_input_tokens INTEGER,
      output_tokens INTEGER, reasoning_output_tokens INTEGER, total_tokens INTEGER,
      limit_percent REAL, limit_window_minutes INTEGER, limit_resets_at INTEGER);
    CREATE TABLE IF NOT EXISTS session_state(
      session_id TEXT PRIMARY KEY, path TEXT, started_at TEXT, updated_at TEXT,
      cwd TEXT, originator TEXT, provider TEXT, model TEXT, effort TEXT,
      task_status TEXT, turn_started_at INTEGER, last_duration_ms INTEGER,
      context_window INTEGER, last_input_tokens INTEGER, last_cached_tokens INTEGER,
      rate_json TEXT);
    CREATE TABLE IF NOT EXISTS desktop_log_files(path TEXT PRIMARY KEY, inode INTEGER, offset INTEGER);
    CREATE TABLE IF NOT EXISTS desktop_selection(key TEXT PRIMARY KEY, value TEXT);
    """)
    version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if not version or version[0] != "5":
        db.execute("DELETE FROM files")
        db.execute("DELETE FROM sessions")
        db.execute("DELETE FROM session_state")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version','5')")
    selection_version = db.execute("SELECT value FROM meta WHERE key='desktop_selection_version'").fetchone()
    if not selection_version or selection_version[0] != "2":
        db.execute("DELETE FROM desktop_log_files")
        db.execute("DELETE FROM desktop_selection")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('desktop_selection_version','2')")


def upsert_state(db, session_id, path, at, **fields):
    db.execute("INSERT OR IGNORE INTO session_state(session_id,path,started_at,updated_at,task_status) VALUES (?,?,?,?,?)",
               (session_id, path, at, at, "idle"))
    fields["path"] = path
    fields["updated_at"] = at
    assignments = ",".join(f"{key}=?" for key in fields)
    db.execute(f"UPDATE session_state SET {assignments} WHERE session_id=? AND updated_at<=?",
               (*fields.values(), session_id, at))


def relevant_files(now):
    # Calendar month and recent 30-day chart, whichever reaches farther back.
    count = max(30, now.day)
    for n in range(count):
        day = (now.date() - timedelta(days=n)).strftime("%Y/%m/%d")
        yield n, (ROOT / day).glob("*.jsonl")


def visible_desktop_session(db, now):
    """Follow the foreground Codex chat view, independent of turn activity."""
    events = []
    for age in range(2):
        day = (now.date() - timedelta(days=age)).strftime("%Y/%m/%d")
        for path in (DESKTOP_LOG_ROOT / day).glob("*.log"):
            stat = path.stat()
            key = str(path)
            old = db.execute("SELECT inode,offset FROM desktop_log_files WHERE path=?", (key,)).fetchone()
            offset = old[1] if old and old[0] == stat.st_ino and old[1] <= stat.st_size else 0
            if offset == stat.st_size:
                continue
            with path.open("rb") as stream:
                stream.seek(offset)
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        stream.seek(start)
                        break
                    if not any(marker in line for marker in (b"thread_stream_view_activity_changed",
                                                            b"browser sidebar owner sync", b"method=thread/queue/list")):
                        continue
                    decoded = line.decode("utf-8", errors="replace")
                    match = VIEW_EVENT.search(decoded)
                    if match:
                        active, thread_id, focused, window_id, visible = match.groups()
                        web = WEB_CONTENTS.search(decoded)
                        if active == "true" and focused == "true" and visible == "true":
                            events.append((decoded[:24], "view", thread_id, window_id,
                                           web.group(1) if web else None))
                    else:
                        route = ROUTE_EVENT.search(decoded)
                        if route:
                            web_id, thread_id, window_id = route.groups()
                            events.append((decoded[:24], "route", thread_id, window_id, web_id))
                        else:
                            queued = QUEUE_EVENT.search(decoded)
                            if queued:
                                thread_id, web_id = queued.groups()
                                events.append((decoded[:24], "queue", thread_id, None, web_id))
                offset = stream.tell()
            db.execute("INSERT OR REPLACE INTO desktop_log_files VALUES (?,?,?)", (key, stat.st_ino, offset))
    saved = dict(db.execute("SELECT key,value FROM desktop_selection"))
    thread_id = saved.get("thread_id")
    window_id = saved.get("window_id")
    web_id = saved.get("web_id")
    for _, kind, candidate, event_window, event_web in sorted(events, key=lambda event: event[0]):
        if kind == "view":
            thread_id, window_id, web_id = candidate, event_window, event_web
        elif kind == "route" and (window_id is None or event_window == window_id):
            thread_id, window_id, web_id = candidate, event_window, event_web
        elif kind == "queue" and (web_id is None or event_web == web_id):
            thread_id, web_id = candidate, event_web
    if thread_id:
        db.execute("INSERT OR REPLACE INTO desktop_selection VALUES ('thread_id',?)", (thread_id,))
    if window_id:
        db.execute("INSERT OR REPLACE INTO desktop_selection VALUES ('window_id',?)", (window_id,))
    if web_id:
        db.execute("INSERT OR REPLACE INTO desktop_selection VALUES ('web_id',?)", (web_id,))
    return thread_id


def scan_file(db, path, usage_only=False):
    stat = path.stat()
    key = str(path)
    old = db.execute("SELECT inode, offset FROM files WHERE path=?", (key,)).fetchone()
    reset = old is not None and (old[0] != stat.st_ino or old[1] > stat.st_size)
    if reset:
        db.execute("DELETE FROM usage WHERE session_id IN (SELECT session_id FROM sessions WHERE path=?)", (key,))
        db.execute("DELETE FROM sessions WHERE path=?", (key,))
        db.execute("DELETE FROM session_state WHERE path=?", (key,))
    offset = old[1] if old and not reset else 0
    if offset == stat.st_size:
        return
    match = SESSION_ID_IN_NAME.search(path.stem)
    session_id = match.group(0) if match else path.stem
    with path.open("rb") as file:
        file.seek(offset)
        while True:
            line_start = file.tell()
            line = file.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                file.seek(line_start)
                break
            if usage_only and b'token_usage_record' not in line:
                continue
            try:
                item = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            payload = item.get("payload") or {}
            timestamp = item.get("timestamp") or ""
            if item.get("type") == "session_meta":
                session_id = payload.get("id") or payload.get("session_id") or session_id
                upsert_state(db, session_id, key, timestamp,
                             started_at=payload.get("timestamp") or timestamp,
                             cwd=payload.get("cwd"), originator=payload.get("originator"),
                             provider=payload.get("model_provider"))
            elif item.get("type") == "turn_context":
                upsert_state(db, session_id, key, timestamp,
                             model=payload.get("model"), effort=payload.get("effort"), cwd=payload.get("cwd"))
            elif item.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                settings = payload.get("thread_settings") or {}
                mapping = {"model": "model", "reasoning_effort": "effort",
                           "model_provider_id": "provider", "cwd": "cwd"}
                changes = {target: settings[source] for source, target in mapping.items() if source in settings}
                if changes:
                    upsert_state(db, session_id, key, timestamp, **changes)
            elif item.get("type") == "token_usage_record":
                response_id = payload.get("response_id")
                usage = payload.get("usage")
                if response_id and usage:
                    db.execute("INSERT OR REPLACE INTO usage VALUES (?,?,?,?,?,?,?,?,?)",
                               (response_id, payload.get("thread_id") or payload.get("session_id") or session_id,
                                timestamp, *values(usage)))
            elif item.get("type") == "event_msg" and payload.get("type") == "task_started":
                upsert_state(db, session_id, key, timestamp, task_status="running",
                             turn_started_at=payload.get("started_at"),
                             context_window=payload.get("model_context_window"))
            elif item.get("type") == "event_msg" and payload.get("type") == "task_complete":
                upsert_state(db, session_id, key, timestamp, task_status="idle",
                             last_duration_ms=payload.get("duration_ms"))
            elif item.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                total = info.get("total_token_usage")
                if total:
                    all_limits = payload.get("rate_limits") or {}
                    limits = all_limits.get("primary") or {}
                    previous = db.execute("SELECT at FROM sessions WHERE session_id=?", (session_id,)).fetchone()
                    if not previous or previous[0] <= timestamp:
                        db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (session_id, key, timestamp, *values(total),
                                    limits.get("used_percent"), limits.get("window_minutes"), limits.get("resets_at")))
                    last = info.get("last_token_usage") or {}
                    upsert_state(db, session_id, key, timestamp,
                                 context_window=info.get("model_context_window"),
                                 last_input_tokens=last.get("input_tokens"),
                                 last_cached_tokens=last.get("cached_input_tokens"),
                                 rate_json=json.dumps(all_limits))
        offset = file.tell()
    db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (key, stat.st_ino, offset, stat.st_size))


def usage_dict(row):
    return dict(zip(FIELDS, row or (0,) * len(FIELDS)))


def sum_usage(db, since):
    cols = ",".join(f"COALESCE(SUM({name}),0)" for name in FIELDS)
    return usage_dict(db.execute(f"SELECT {cols} FROM usage WHERE at>=?", (since,)).fetchone())


def session_info(db, row, now):
    columns = ("id", "updated_at", *FIELDS, "limit_percent", "limit_window_minutes", "limit_resets_at",
               "started_at", "cwd", "originator", "provider", "model", "effort", "task_status",
               "turn_started_at", "last_duration_ms", "context_window", "last_input_tokens", "last_cached_tokens", "rate_json")
    data = dict(zip(columns, row))
    usage = {key: data.pop(key) or 0 for key in FIELDS}
    data["usage"] = usage
    data["rate_limit"] = {"used_percent": data.pop("limit_percent"),
                          "window_minutes": data.pop("limit_window_minutes"),
                          "resets_at": data.pop("limit_resets_at")}
    raw_rates = data.pop("rate_json")
    data["all_rate_limits"] = json.loads(raw_rates) if raw_rates else {}
    # An unfinished turn can be an interrupted process. Do not report stale runs as active.
    if data["task_status"] == "running" and data["updated_at"]:
        try:
            updated = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            if (now - updated).total_seconds() > 120:
                data["task_status"] = "unconfirmed"
        except ValueError:
            pass
    return data


def daily_usage(db, today, count):
    days = [(today.date() - timedelta(days=n)).isoformat() for n in range(count - 1, -1, -1)]
    totals = {day: 0 for day in days}
    for at, tokens in db.execute("SELECT at,total_tokens FROM usage WHERE at>=?", ((today - timedelta(days=count-1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),)):
        try:
            day = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            continue
        if day in totals:
            totals[day] += tokens
    return [{"date": day, "total_tokens": totals[day]} for day in days]


def read_catalog(selected_id=None):
    """Read persisted per-thread settings, never infer foreground chat from activity."""
    path = ROOT.parent / "state_5.sqlite"
    if not path.exists():
        return []
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as source:
            source.row_factory = sqlite3.Row
            columns = {row[1] for row in source.execute("PRAGMA table_info(threads)")}
            fields = [name for name in ("id", "name", "title", "model", "reasoning_effort", "cwd", "rollout_path") if name in columns]
            order = "updated_at_ms" if "updated_at_ms" in columns else "updated_at"
            sql = f"SELECT {','.join(fields)} FROM threads"
            rows = list(source.execute(sql + f" WHERE archived=0 ORDER BY {order} DESC LIMIT 50"))
            if selected_id and not any(row["id"] == selected_id for row in rows):
                rows.extend(source.execute(sql + " WHERE id=?", (selected_id,)))
            catalog = [dict(row) for row in rows]
            for entry in catalog:
                label = entry.get("name") or entry.get("title") or entry["id"][:8]
                label = " ".join(label.split())
                entry["title"] = label[:64] + ("…" if len(label) > 64 else "")
            return catalog
    except (sqlite3.Error, ValueError):
        return []


def snapshot(selected_id=None):
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(CACHE, timeout=10)) as db:
        init(db)
        desktop_id = visible_desktop_session(db, now) if selected_id is None else None
        target_id = selected_id or desktop_id
        catalog = read_catalog(target_id)
        catalog_by_id = {entry["id"]: entry for entry in catalog}
        for age, paths in relevant_files(now):
            for path in paths:
                scan_file(db, path, usage_only=age >= 7)
        selected_path = catalog_by_id.get(target_id, {}).get("rollout_path")
        if selected_path:
            path = Path(selected_path).resolve()
            try:
                path.relative_to(ROOT.resolve())
            except ValueError:
                pass
            else:
                if path.is_file():
                    scan_file(db, path)
        retention = (today - timedelta(days=max(29, today.day - 1))).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        seven_start = (today - timedelta(days=6)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        db.execute("DELETE FROM usage WHERE at<?", (retention,))
        db.commit()
        cols = ",".join(f"COALESCE(s.{name},0)" for name in FIELDS)
        rows = db.execute(f"SELECT st.session_id,st.updated_at,{cols},s.limit_percent,s.limit_window_minutes,s.limit_resets_at,"
                          "st.started_at,st.cwd,st.originator,st.provider,st.model,st.effort,st.task_status,"
                          "st.turn_started_at,st.last_duration_ms,st.context_window,st.last_input_tokens,st.last_cached_tokens,st.rate_json "
                          "FROM session_state st LEFT JOIN sessions s ON st.session_id=s.session_id "
                          "ORDER BY CASE WHEN st.session_id=? THEN 0 ELSE 1 END, st.updated_at DESC LIMIT 20", (target_id,)).fetchall()
        sessions = [session_info(db, row, now) for row in rows]
        for session in sessions:
            metadata = catalog_by_id.get(session["id"], {})
            session["title"] = metadata.get("title")
            for field, source in (("model", "model"), ("effort", "reasoning_effort"), ("cwd", "cwd")):
                if metadata.get(source) is not None:
                    session[field] = metadata[source]
        available = [{"id": entry["id"], "title": entry.get("title") or entry["id"][:8]} for entry in catalog]
        if not available:
            available = [{"id": session["id"], "title": session.get("title") or session["id"][:8]} for session in sessions]
        current = next((session for session in sessions if session["id"] == target_id), None) if target_id else (sessions[0] if sessions else None)
        result = {"current_session": current,
                "available_sessions": available,
                "selection_mode": "selected" if selected_id else ("desktop_view" if desktop_id else "latest_activity"),
                "recent_sessions": sessions,
                "today": sum_usage(db, today.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")),
                "this_week": sum_usage(db, week.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")),
                "this_month": sum_usage(db, month.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")),
                "seven_days": sum_usage(db, seven_start),
                "daily_usage": daily_usage(db, today, 7),
                "month_daily_usage": daily_usage(db, today, today.day),
                "updated_at": now.isoformat(), "source": str(ROOT)}
    if ROOT == Path.home() / ".codex/sessions" and os.environ.get("CODEX_PULSE_DISABLE_ACCOUNT") != "1":
        result["account"] = read_account()
    else:
        result["account"] = None
    return result


if __name__ == "__main__":
    try:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--session")
        args = parser.parse_args()
        print(json.dumps(snapshot(args.session), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
