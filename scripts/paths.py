"""Shared application data location."""
from pathlib import Path


def data_directory(home=None):
    home = Path(home) if home is not None else Path.home()
    return home / ".codex/codex-dashboard"
