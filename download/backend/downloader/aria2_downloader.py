"""
aria2c subprocess downloader.
Uses multi-connection downloading for maximum speed on direct file URLs.
Progress is tracked by monitoring the output file size.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from config import config
from downloader.base import BaseDownloader
from utils import get_logger
from utils.helpers import extract_filename_from_url

log = get_logger("aria2")


class Aria2Downloader(BaseDownloader):
    async def get_name(self) -> str:
        return "aria2"

    async def download(
        self,
        url: str,
        output_dir: Path,
        *,
        filename: str | None = None,
        headers: dict[str, str] | None = None,
        cookies: str | None = None,
        format_id: str | None = None,   # unused
        progress_callback=None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or extract_filename_from_url(url)

        cmd: list[str] = [
            config.ARIA2C_PATH,
            f"--max-connection-per-server={config.ARIA2_CONNECTIONS}",
            f"--split={config.ARIA2_SPLIT}",
            f"--min-split-size={config.ARIA2_MIN_SPLIT_SIZE}",
            "--file-allocation=none",
            "--continue=true",
            "--auto-file-renaming=false",
            "--allow-overwrite=false",
            "--console-log-level=notice",
            "--summary-interval=1",
            "--download-result=full",
            "-d", str(output_dir),
            "-o", fname,
        ]
        if headers:
            for k, v in headers.items():
                cmd.extend(["--header", f"{k}: {v}"])
        if cookies:
            cmd.extend(["--header", f"Cookie: {cookies}"])
        cmd.append(url)

        log.info("Running: %s", " ".join(cmd))

        # Pre-flight HEAD to learn total size (for progress %)
        total_size = await self._get_content_length(url, headers, cookies)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        output_path = output_dir / fname
        monitor_task: asyncio.Task | None = None

        if total_size and total_size > 0 and progress_callback:
            monitor_task = asyncio.create_task(
                self._monitor_file(output_path, total_size, progress_callback)
            )

        stderr_lines: list[str] = []

        async def _drain(stream):
            async for raw in stream:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    stderr_lines.append(line)
                    log.debug("[aria2] %s", line)
                    # Also try to parse any percentage from summary
                    if progress_callback:
                        m = re.search(r"\((\d+)%\)", line)
                        if m:
                            await progress_callback({"progress": float(m.group(1))})

        await asyncio.gather(_drain(proc.stdout), _drain(proc.stderr))
        retcode = await proc.wait()

        if monitor_task:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

        if retcode != 0:
            tail = "\n".join(stderr_lines[-5:])
            raise RuntimeError(f"aria2c exited with code {retcode}:\n{tail}")

        if not output_path.exists():
            raise FileNotFoundError(f"aria2c completed but file not found: {output_path}")

        if progress_callback:
            await progress_callback({"progress": 100.0})

        return output_path

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    async def _monitor_file(
        path: Path, total: int, callback, interval: float = 0.5
    ):
        """Periodically check the file size and emit progress."""
        try:
            while True:
                await asyncio.sleep(interval)
                if path.exists():
                    current = path.stat().st_size
                    pct = min(current / total * 100, 99.9)
                    speed_str = ""
                    await callback({"progress": round(pct, 1), "speed": speed_str})
        except asyncio.CancelledError:
            return

    @staticmethod
    async def _get_content_length(
        url: str,
        headers: dict[str, str] | None,
        cookies: str | None,
    ) -> int | None:
        import aiohttp

        try:
            req_h = dict(headers) if headers else {}
            req_h.setdefault(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            )
            if cookies:
                req_h["Cookie"] = cookies
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as s:
                async with s.head(url, headers=req_h, allow_redirects=True) as r:
                    cl = r.headers.get("Content-Length")
                    return int(cl) if cl and cl.isdigit() else None
        except Exception:
            return None