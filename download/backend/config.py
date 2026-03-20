"""
Central configuration for the download backend.
All values can be overridden via environment variables.
"""

import os
from pathlib import Path


class Config:
    # ── Server ──────────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8765"))

    # ── Paths ───────────────────────────────────────────────────────────
    DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "./downloads")).resolve()
    YTDLP_PATH: str = os.getenv("YTDLP_PATH", "yt-dlp")
    ARIA2C_PATH: str = os.getenv("ARIA2C_PATH", "aria2c")

    # ── Concurrency ────────────────────────────────────────────────────
    MAX_CONCURRENT: int = int(os.getenv("MAX_CONCURRENT", "3"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

    # ── aria2 tuning ───────────────────────────────────────────────────
    ARIA2_CONNECTIONS: int = int(os.getenv("ARIA2_CONNECTIONS", "16"))
    ARIA2_SPLIT: int = int(os.getenv("ARIA2_SPLIT", "16"))
    ARIA2_MIN_SPLIT_SIZE: str = os.getenv("ARIA2_MIN_SPLIT_SIZE", "1M")

    # ── Logging ────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "downloader.log")

    # ── CORS ───────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["*"]

    # ── Cleanup ────────────────────────────────────────────────────────
    TASK_TTL_SECONDS: int = int(os.getenv("TASK_TTL_SECONDS", "3600"))


config = Config()