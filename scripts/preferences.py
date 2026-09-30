"""Shared, non-sensitive desktop display preferences."""
from __future__ import annotations

import json
import os
from pathlib import Path

PATH = Path(os.environ.get("CODEX_PULSE_PREFERENCES", str(Path.home() / ".codex/codex-pulse/preferences.json")))
DEFAULTS = {
    "language": "en",
    "theme": "system",
    "show_context": True,
    "show_breakdown": True,
    "show_local_usage": True,
    "show_trend": True,
    "show_advanced": False,
    "accent": "cyan",
}


def read_preferences(path=PATH):
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    result = dict(DEFAULTS)
    if saved.get("language") in ("en", "zh"):
        result["language"] = saved["language"]
    if saved.get("theme") in ("system", "dark", "light"):
        result["theme"] = saved["theme"]
    if saved.get("accent") in ("cyan", "violet", "green"):
        result["accent"] = saved["accent"]
    for key in ("show_context", "show_breakdown", "show_local_usage", "show_trend", "show_advanced"):
        if isinstance(saved.get(key), bool):
            result[key] = saved[key]
    return result


def save_preferences(settings, path=PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = read_preferences(path)
    merged.update({key: value for key, value in settings.items() if key in DEFAULTS})
    merged = {key: read_preferences_value(key, value) for key, value in merged.items()}
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(merged, stream, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return merged


def read_preferences_value(key, value):
    if key == "language":
        return value if value in ("en", "zh") else DEFAULTS[key]
    if key == "theme":
        return value if value in ("system", "dark", "light") else DEFAULTS[key]
    if key == "accent":
        return value if value in ("cyan", "violet", "green") else DEFAULTS[key]
    return value if isinstance(value, bool) else DEFAULTS[key]
