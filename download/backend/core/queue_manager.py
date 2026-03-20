"""
Async download queue with concurrency control, retry logic, and progress tracking.
"""

from __future__ import annotations

import asyncio
import uuid
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from config import config
from core.router import select_method
from core.analyzer import URLAnalyzer
from downloader.ytdlp_downloader import YtdlpDownloader
from downloader.aria2_downloader import Aria2Downloader
from downloader.direct_downloader import DirectDownloader
from api.models import TaskStatus
from utils import get_logger

log = get_logger("queue")


@dataclass
class DownloadTask:
    task_id: str
    url: str
    method: str
    status: str = "queued"              # queued | downloading | completed | failed | cancelled | retrying
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    filename: str = ""
    error: str = ""
    retries: int = 0
    output_name: str | None = None
    headers: dict[str, str] | None = None
    cookies: str | None = None
    format_id: str | None = None
    page_url: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    _process_task: asyncio.Task | None = field(default=None, repr=False)

    def to_status(self) -> TaskStatus:
        return TaskStatus(
            task_id=self.task_id,
            url=self.url,
            status=self.status,
            progress=self.progress,
            speed=self.speed,
            eta=self.eta,
            filename=self.filename,
            method=self.method,
            error=self.error,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            retries=self.retries,
        )


class QueueManager:
    def __init__(self) -> None:
        self.tasks: dict[str, DownloadTask] = {}
        self._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
        self._ytdlp = YtdlpDownloader()
        self._aria2 = Aria2Downloader()
        self._direct = DirectDownloader()
        self._analyzer = URLAnalyzer()

    # ── public API ──────────────────────────────────────────────────────

    async def add_task(
        self,
        url: str,
        method: str | None = None,
        output_name: str | None = None,
        headers: dict[str, str] | None = None,
        cookies: str | None = None,
        format_id: str | None = None,
        page_url: str | None = None,
    ) -> str:
        task_id = uuid.uuid4().hex[:10]

        # Auto-detect method if not specified
        if not method:
            try:
                analysis = await self._analyzer.analyze(url, headers=headers, cookies=cookies)
                method = select_method(url, analysis.media_type, None)
                if not output_name and analysis.title:
                    output_name = analysis.title
            except Exception:
                method = select_method(url, "unknown", None)
        else:
            method = select_method(url, "", method)

        task = DownloadTask(
            task_id=task_id,
            url=url,
            method=method,
            output_name=output_name,
            headers=headers,
            cookies=cookies,
            format_id=format_id,
            page_url=page_url,
        )
        self.tasks[task_id] = task
        task._process_task = asyncio.create_task(self._run(task))
        log.info("Task %s queued: %s  method=%s", task_id, url, method)
        return task_id

    def get_status(self, task_id: str) -> TaskStatus | None:
        task = self.tasks.get(task_id)
        return task.to_status() if task else None

    def get_all_status(self) -> list[TaskStatus]:
        self._cleanup_old()
        return [t.to_status() for t in self.tasks.values()]

    async def cancel_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if not task or task.status in ("completed", "cancelled"):
            return False
        task.status = "cancelled"
        if task._process_task and not task._process_task.done():
            task._process_task.cancel()
        log.info("Task %s cancelled", task_id)
        return True

    def clear_finished(self) -> int:
        to_remove = [
            tid for tid, t in self.tasks.items()
            if t.status in ("completed", "failed", "cancelled")
        ]
        for tid in to_remove:
            del self.tasks[tid]
        return len(to_remove)

    # ── internals ───────────────────────────────────────────────────────

    async def _run(self, task: DownloadTask) -> None:
        """Acquire a semaphore slot, then execute with retries."""
        async with self._semaphore:
            for attempt in range(config.MAX_RETRIES + 1):
                if task.status == "cancelled":
                    return
                task.status = "downloading"
                task.started_at = datetime.now(timezone.utc)
                task.retries = attempt
                try:
                    await self._execute(task)
                    task.status = "completed"
                    task.progress = 100.0
                    task.completed_at = datetime.now(timezone.utc)
                    log.info("Task %s completed: %s", task.task_id, task.filename)
                    return
                except asyncio.CancelledError:
                    task.status = "cancelled"
                    return
                except Exception as exc:
                    log.error("Task %s attempt %d failed: %s", task.task_id, attempt + 1, exc)
                    if attempt < config.MAX_RETRIES:
                        wait = 2 ** attempt
                        task.status = "retrying"
                        task.error = f"Retry {attempt + 1}/{config.MAX_RETRIES}: {exc}"
                        await asyncio.sleep(wait)
                    else:
                        task.status = "failed"
                        task.error = str(exc)
                        task.completed_at = datetime.now(timezone.utc)

    async def _execute(self, task: DownloadTask) -> None:
        downloader = {
            "ytdlp": self._ytdlp,
            "aria2": self._aria2,
            "direct": self._direct,
        }.get(task.method, self._direct)

        async def _progress(data: dict):
            if task.status == "cancelled":
                raise asyncio.CancelledError()
            if "progress" in data:
                task.progress = data["progress"]
            if "speed" in data:
                task.speed = data["speed"]
            if "eta" in data:
                task.eta = data["eta"]
            if "filename" in data:
                task.filename = data["filename"]

        result_path = await downloader.download(
            url=task.url,
            output_dir=config.DOWNLOAD_DIR,
            filename=task.output_name,
            headers=task.headers,
            cookies=task.cookies,
            format_id=task.format_id,
            progress_callback=_progress,
        )
        task.filename = result_path.name

    def _cleanup_old(self) -> None:
        """Remove finished tasks older than TTL."""
        now = time.time()
        to_rm = []
        for tid, t in self.tasks.items():
            if t.status in ("completed", "failed", "cancelled") and t.completed_at:
                age = now - t.completed_at.timestamp()
                if age > config.TASK_TTL_SECONDS:
                    to_rm.append(tid)
        for tid in to_rm:
            del self.tasks[tid]


# Singleton — created on import, but the event loop must already be running
# when add_task() is called (which it will be under FastAPI/uvicorn).
queue_manager = QueueManager()