"""Rotating file logging, so a windowed `.exe` build still leaves a trail."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from loancalc.paths import log_dir

_configured = False
_ROOT = "loancalc"


def get_logger(name: str) -> logging.Logger:
    """Return a module logger, configuring the shared file handler once."""
    global _configured
    if not _configured:
        handler = RotatingFileHandler(
            log_dir() / "loancalc.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger(_ROOT)
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        _configured = True
    return logging.getLogger(name)
