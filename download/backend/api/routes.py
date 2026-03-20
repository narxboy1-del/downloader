"""
FastAPI route definitions.  All heavy lifting is delegated to the core modules.
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException

from api.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    DownloadRequest,
    DownloadResponse,
    TaskStatus,
    AllTasksResponse,
    HealthResponse,
)
from core.analyzer import URLAnalyzer
from core.queue_manager import queue_manager
from utils import get_logger

router = APIRouter(prefix="/api")
log = get_logger("routes")
analyzer = URLAnalyzer()


# ── Analyze ─────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_url(req: AnalyzeRequest):
    log.info("Analyze request: %s", req.url)
    try:
        result = await analyzer.analyze(req.url, headers=req.headers, cookies=req.cookies)
        return result
    except Exception as exc:
        log.error("Analysis failed for %s: %s", req.url, exc)
        raise HTTPException(status_code=400, detail=str(exc))


# ── Download ────────────────────────────────────────────────────────────

@router.post("/download", response_model=DownloadResponse)
async def start_download(req: DownloadRequest):
    log.info("Download request: %s  method=%s", req.url, req.method or "auto")
    try:
        task_id = await queue_manager.add_task(
            url=req.url,
            method=req.method,
            output_name=req.output_name,
            headers=req.headers,
            cookies=req.cookies,
            format_id=req.format_id,
            page_url=req.page_url,
        )
        return DownloadResponse(task_id=task_id, status="queued")
    except Exception as exc:
        log.error("Failed to queue download: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Status ──────────────────────────────────────────────────────────────

@router.get("/status", response_model=AllTasksResponse)
async def all_task_status():
    tasks = queue_manager.get_all_status()
    return AllTasksResponse(tasks=tasks)


@router.get("/status/{task_id}", response_model=TaskStatus)
async def single_task_status(task_id: str):
    status = queue_manager.get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


# ── Cancel ──────────────────────────────────────────────────────────────

@router.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    ok = await queue_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or already finished")
    return {"task_id": task_id, "status": "cancelled"}


# ── Clear ───────────────────────────────────────────────────────────────

@router.delete("/tasks/clear")
async def clear_finished():
    count = queue_manager.clear_finished()
    return {"cleared": count}


# ── Health ──────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    import shutil
    from config import config

    yt = shutil.which(config.YTDLP_PATH) is not None
    ar = shutil.which(config.ARIA2C_PATH) is not None
    active = sum(1 for t in queue_manager.tasks.values() if t.status == "downloading")
    queued = sum(1 for t in queue_manager.tasks.values() if t.status == "queued")

    return HealthResponse(
        status="ok",
        ytdlp_available=yt,
        aria2_available=ar,
        download_dir=str(config.DOWNLOAD_DIR),
        active_tasks=active,
        queued_tasks=queued,
    )