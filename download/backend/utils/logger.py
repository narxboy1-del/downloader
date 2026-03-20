"""
Structured logging for the backend.
Console output uses colour. File output is plain text.
"""

import logging
import sys
from pathlib import Path
from config import config


_COLOURS = {
    "DEBUG": "\033[36m",     # cyan
    "INFO": "\033[32m",      # green
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[35m",  # magenta
}
_RESET = "\033[0m"


class ColouredFormatter(logging.Formatter):
    """Adds ANSI colours to console log output."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _COLOURS.get(record.levelname, "")
        record.levelname = f"{colour}{record.levelname:<8}{_RESET}"
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    # ── Console handler ─────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        ColouredFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(console)

    # ── File handler ────────────────────────────────────────────────
    log_path = Path(config.LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_h = logging.FileHandler(str(log_path), encoding="utf-8")
    file_h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
    )
    logger.addHandler(file_h)

    return logger