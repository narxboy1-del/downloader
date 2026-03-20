"""
Pure-Python async HTTP downloader using aiohttp.
Fallback when neither yt-dlp nor aria2 can be used.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp

from downloader.base import BaseDownloader
from utils import get_logger
from utils.helpers import extract_filename_from_url, format_bytes

log = get_logger("direct")

_CHUNK = 64 * 1024  # 64 KB


class DirectDownloader(BaseDownloader):
    async def get_name(self) -> str:
        return "direct"

    async def download(
        self,
        url: str,
        output_dir: Path,
        *,
        filename: str | None = None,
        headers: dict[str, str] | None = None,
        cookies: str | None = None,
        format_id: str | None = None,
        progress_callback=None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or extract_filename_from_url(url)
        output_path = output_dir / fname

        req_headers = dict(headers) if headers else {}
        req_headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        if cookies:
            req_headers["Cookie"] = cookies

        timeout = aiohttp.ClientTimeout(total=None, sock_read=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=req_headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} for {url}")

                total = int(resp.headers.get("Content-Length", 0)) or None
                downloaded = 0

                # Try to get filename from Content-Disposition
                cd = resp.headers.get("Content-Disposition", "")
                if "filename=" in cd:
                    import re
                    m = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\r\n]+)', cd, re.I)
                    if m:
                        from utils.helpers import sanitize_filename
                        fname = sanitize_filename(m.group(1))
                        output_path = output_dir / fname

                log.info(
                    "Downloading %s → %s  (size: %s)",
                    url,
                    output_path.name,
                    format_bytes(total) if total else "unknown",
                )

                if progress_callback:
                    await progress_callback({"filename": output_path.name})

                with open(output_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(_CHUNK):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total:
                            pct = downloaded / total * 100
                            await progress_callback({"progress": round(pct, 1)})

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Download produced empty or missing file")

        if progress_callback:
            await progress_callback({"progress": 100.0})

        log.info("Download complete: %s (%s)", output_path.name, format_bytes(output_path.stat().st_size))
        return output_path