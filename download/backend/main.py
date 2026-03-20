"""
Application entry-point.  Run with:

    cd backend
    python main.py
"""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from api.routes import router
from utils import get_logger

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ─────────────────────────────────────────────────────
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Download directory: %s", config.DOWNLOAD_DIR)

    yt = shutil.which(config.YTDLP_PATH)
    ar = shutil.which(config.ARIA2C_PATH)
    log.info("yt-dlp   : %s", yt or "NOT FOUND ⚠️")
    log.info("aria2c   : %s", ar or "NOT FOUND ⚠️")
    if not yt and not ar:
        log.warning("Neither yt-dlp nor aria2c found — only direct downloads will work.")

    log.info("Server starting on http://%s:%s", config.HOST, config.PORT)
    yield
    # ── Shutdown ────────────────────────────────────────────────────
    log.info("Server shutting down")


app = FastAPI(
    title="Hybrid Media Downloader",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )