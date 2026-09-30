import json
import tempfile
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collector


class CollectorTests(unittest.TestCase):
    def test_upgrade_reindexes_history_for_90_day_chart(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO meta VALUES ('schema_version','5')")
            db.execute("INSERT INTO meta VALUES ('history_scan_day','2026-09-30')")
            collector.init(db)
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "8")
            self.assertIsNone(db.execute("SELECT value FROM meta WHERE key='history_scan_day'").fetchone())

    def test_continued_rollout_keeps_original_session_id(self):
        with tempfile.TemporaryDirectory() as temp:
            original_root, original_cache, original_logs = collector.ROOT, collector.CACHE, collector.DESKTOP_LOG_ROOT
            try:
                collector.ROOT = Path(temp) / "sessions"
                collector.CACHE = Path(temp) / "cache.sqlite3"
                collector.DESKTOP_LOG_ROOT = Path(temp) / "desktop-logs"
                folder = collector.ROOT / datetime.now().astimezone().strftime("%Y/%m/%d")
                folder.mkdir(parents=True)
                thread_id = "00000000-0000-0000-0000-000000000011"
                continuation_id = "00000000-0000-0000-0000-000000000022"
                continued = folder / f"rollout-test-{thread_id}_{continuation_id}.jsonl"
                original = folder / f"rollout-test-{thread_id}.jsonl"
                now = datetime.now().astimezone()
                def event(at, kind):
                    return json.dumps({"timestamp": at.isoformat(), "type": "event_msg", "payload": {"type": kind}}) + "\n"
                continued.write_text(json.dumps({"timestamp": (now + timedelta(seconds=1)).isoformat(),
                                                "type": "session_meta", "payload": {"id": thread_id}}) + "\n"
                                     + event(now + timedelta(seconds=1), "task_started"))
                original.write_text(json.dumps({"timestamp": now.isoformat(), "type": "session_meta",
                                                "payload": {"id": thread_id}}) + "\n"
                                    + event(now, "task_complete"))
                self.assertEqual(collector.snapshot(thread_id)["current_session"]["task_status"], "running")
                with continued.open("a") as stream:
                    stream.write(event(now + timedelta(seconds=2), "task_complete"))
                self.assertEqual(collector.snapshot(thread_id)["current_session"]["task_status"], "idle")
                with closing(sqlite3.connect(collector.CACHE)) as db:
                    ids = [row[0] for row in db.execute("SELECT session_id FROM session_state")]
                self.assertEqual(ids, [thread_id])
            finally:
                collector.ROOT, collector.CACHE, collector.DESKTOP_LOG_ROOT = original_root, original_cache, original_logs

    def test_incremental_snapshot_deduplicates_responses(self):
        with tempfile.TemporaryDirectory() as temp:
            original_root, original_cache, original_logs = collector.ROOT, collector.CACHE, collector.DESKTOP_LOG_ROOT
            try:
                root = Path(temp) / "sessions"
                day = datetime.now().astimezone().strftime("%Y/%m/%d")
                folder = root / day
                folder.mkdir(parents=True)
                session_id = "00000000-0000-0000-0000-000000000001"
                path = folder / f"rollout-test-{session_id}.jsonl"
                collector.ROOT = root
                collector.CACHE = Path(temp) / "cache.sqlite3"
                collector.DESKTOP_LOG_ROOT = Path(temp) / "desktop-logs"
                at = datetime.now().astimezone().isoformat()

                def record(response, total):
                    return {"timestamp": at, "type": "token_usage_record", "payload": {
                        "thread_id": session_id, "response_id": response,
                        "usage": {"input_tokens": total - 2, "output_tokens": 2, "total_tokens": total}}}

                def write(item):
                    with path.open("a") as stream:
                        stream.write(json.dumps(item) + "\n")

                write({"timestamp": at, "type": "session_meta", "payload": {"id": session_id}})
                write({"timestamp": at, "type": "turn_context", "payload": {
                    "model": "gpt-test", "effort": "medium", "cwd": "/tmp/project"}})
                write({"timestamp": at, "type": "event_msg", "payload": {
                    "type": "task_started", "started_at": 1, "model_context_window": 100}})
                write(record("response-1", 10))
                write(record("response-1", 10))
                write({"timestamp": at, "type": "event_msg", "payload": {
                    "type": "token_count", "info": {"last_token_usage": {"input_tokens": 8},
                    "total_token_usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}}}})
                first = collector.snapshot()
                self.assertEqual(first["today"]["total_tokens"], 10)
                self.assertEqual(first["this_week"]["total_tokens"], 10)
                self.assertEqual(first["this_month"]["total_tokens"], 10)
                self.assertEqual(len(first["month_daily_usage"]), datetime.now().astimezone().day)
                self.assertEqual(len(first["history_daily_usage"]), 90)
                self.assertEqual(first["current_session"]["usage"]["total_tokens"], 10)
                self.assertEqual(first["current_session"]["model"], "gpt-test")
                self.assertEqual(first["current_session"]["task_status"], "running")
                self.assertEqual(first["current_session"]["last_input_tokens"], 8)
                write(record("response-2", 20))
                write({"timestamp": at, "type": "event_msg", "payload": {"type": "task_complete", "duration_ms": 1234}})
                second = collector.snapshot()
                self.assertEqual(second["today"]["total_tokens"], 30)
                self.assertEqual(second["current_session"]["task_status"], "idle")
                self.assertEqual(collector.snapshot()["today"]["total_tokens"], 30)
                # Changing the model without starting a new turn must update the panel.
                write({"timestamp": at, "type": "event_msg", "payload": {
                    "type": "thread_settings_applied", "thread_settings": {"model": "gpt-new", "reasoning_effort": "high"}}})
                changed = collector.snapshot(session_id)["current_session"]
                self.assertEqual(changed["model"], "gpt-new")
                self.assertEqual(changed["effort"], "high")
                self.assertEqual(collector.snapshot(session_id)["runtime_signals"]["model_change"]["to"], "gpt-new")
                write({"timestamp": at, "type": "event_msg", "payload": {
                    "type": "thread_settings_applied", "thread_settings": {"reasoning_effort": "low"}}})
                self.assertEqual(collector.snapshot(session_id)["runtime_signals"]["effort_reduction"]["to"], "low")
                self.assertEqual(changed["task_status"], "idle")
                # Persisted picker settings take effect before any new usage event.
                with closing(sqlite3.connect(root.parent / "state_5.sqlite")) as state:
                    state.execute("CREATE TABLE threads(id,title,model,reasoning_effort,cwd,rollout_path,archived,updated_at)")
                    state.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?,?)", (session_id, "Selected chat", "gpt-picker", "low", "/tmp/project", str(path), 0, 1))
                    state.commit()
                self.assertEqual(collector.snapshot(session_id)["current_session"]["model"], "gpt-picker")
                # Another session's later event cannot override a locked selection.
                other_id = "00000000-0000-0000-0000-000000000002"
                other = folder / f"rollout-test-{other_id}.jsonl"
                other.write_text(json.dumps({"timestamp": "2099-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": other_id}}) + "\n")
                self.assertEqual(collector.snapshot()["current_session"]["id"], other_id)
                self.assertEqual(collector.snapshot(session_id)["current_session"]["id"], session_id)
                self.assertIsNone(collector.snapshot("missing")["current_session"])
                # Foreground chat changes, not background token activity, choose the panel session.
                log_dir = collector.DESKTOP_LOG_ROOT / day
                log_dir.mkdir(parents=True)
                log = log_dir / "codex-desktop.log"
                base = datetime.now(timezone.utc)
                def view_event(when, thread_id):
                    stamp = when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
                    return (f"{stamp} info [electron-message-handler] thread_stream_view_activity_changed "
                            f"active=true conversationId={thread_id} rendererWebContentsId=1 "
                            "rendererWindowAppearance=primary rendererWindowFocused=true "
                            "rendererWindowId=1 rendererWindowVisible=true\n")
                log.write_text(view_event(base, session_id))
                self.assertEqual(collector.snapshot()["current_session"]["id"], session_id)
                self.assertEqual(collector.snapshot()["current_session"]["id"], session_id)
                with log.open("a") as stream:
                    stream.write(view_event(base + timedelta(seconds=1), other_id))
                self.assertEqual(collector.snapshot()["current_session"]["id"], other_id)
                # Returning to a cached chat may issue a queue request without a view event.
                def queue_event(when, thread_id, web_id):
                    stamp = when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
                    return (f"{stamp} info [AppServerConnection] response_routed broadcastFallback=false "
                            f"conversationId={thread_id} durationMs=1 errorCode=null hadInternalHandler=false "
                            f"hadPending=true method=thread/queue/list originWebcontentsId={web_id} "
                            "queueWaitMs=0 requestId=test targetDestroyed=false\n")
                with log.open("a") as stream:
                    stream.write(queue_event(base + timedelta(seconds=2), session_id, 1))
                self.assertEqual(collector.snapshot()["current_session"]["id"], session_id)
                # A different window's request cannot take ownership of this panel.
                with log.open("a") as stream:
                    stream.write(queue_event(base + timedelta(seconds=3), other_id, 2))
                self.assertEqual(collector.snapshot()["current_session"]["id"], session_id)
                with log.open("a") as stream:
                    stamp = (base + timedelta(seconds=4)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
                    stream.write(f"{stamp} info [electron-message-handler] IAB_LIFECYCLE received browser "
                                 f"sidebar owner sync browserTabId=null conversationId=none originWebContentsId=1 "
                                 f"ownerRoutePath=/local/{other_id} windowId=1\n")
                self.assertEqual(collector.snapshot()["current_session"]["id"], other_id)
            finally:
                collector.ROOT, collector.CACHE = original_root, original_cache
                collector.DESKTOP_LOG_ROOT = original_logs


if __name__ == "__main__":
    unittest.main()
