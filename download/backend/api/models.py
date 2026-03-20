"""
Pydantic models for the API request / response payloads.
"""

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


# ── Requests ────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    url: str
    page_url: str | None = None
    headers: dict[str, str] | None = None
    cookies: str | None = None


class DownloadRequest(BaseModel):
    url: str
    method: str | None = None            # ytdlp | aria2 | direct  — None = auto
    format_id: str | None = None         # yt-dlp format selector
    output_name: str | None = None
    headers: dict[str, str] | None = None
    cookies: str | None = None
    page_url: str | None = None


class CancelRequest(BaseModel):
    pass  # path param only


# ── Responses ───────────────────────────────────────────────────────────

class FormatInfo(BaseModel):
    format_id: str
    ext: str
    resolution: str | None = None
    filesize: int | None = None
    note: str | None = None


class AnalyzeResponse(BaseModel):
    url: str
    media_type: str                       # mp4 | m3u8 | mpd | page | audio | unknown
    recommended_method: str               # ytdlp | aria2 | direct
    title: str | None = None
    filesize: int | None = None
    formats: list[FormatInfo] = Field(default_factory=list)
    is_playlist: bool = False
    platform: str | None = None


class DownloadResponse(BaseModel):
    task_id: str
    status: str


class TaskStatus(BaseModel):
    task_id: str
    url: str
    status: str                           # queued | downloading | completed | failed | cancelled | retrying
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    filename: str = ""
    method: str = ""
    error: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retries: int = 0


class AllTasksResponse(BaseModel):
    tasks: list[TaskStatus]


class HealthResponse(BaseModel):
    status: str
    ytdlp_available: bool
    aria2_available: bool
    download_dir: str
    active_tasks: int
    queued_tasks: int