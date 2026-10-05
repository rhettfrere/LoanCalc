"""Filesystem locations for user data, logs, and the bundled sample dataset.

Resolved at runtime so the same code works from source, from `uv run`, and from
the Nuitka standalone build.
"""
from __future__ import annotations

import os
import sys
from importlib import resources
from pathlib import Path

APP_NAME = "LoanCalc"
SAMPLE_FILENAME = "raw_30Sept26.csv"
ICON_FILENAME = "loancalc.ico"


def data_dir() -> Path:
    """Per-user writable directory for the database and logs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    directory = base / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def database_path() -> Path:
    return data_dir() / "loancalc.db"


def log_dir() -> Path:
    directory = data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def backup_dir() -> Path:
    directory = data_dir() / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def resource(*parts: str):
    """Traversable for a file bundled under `loancalc/resources/`."""
    return resources.files("loancalc").joinpath("resources", *parts)


def icon_path() -> Path | None:
    try:
        path = Path(str(resource(ICON_FILENAME)))
    except (ModuleNotFoundError, OSError):
        return None
    return path if path.exists() else None


def sample_data_text() -> str | None:
    """Return the bundled starter dataset, or None if it was not packaged."""
    try:
        return resource("sample_data", SAMPLE_FILENAME).read_text(encoding="utf-8-sig")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None
