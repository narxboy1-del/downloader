"""
URL analysis engine.
Determines media type, recommended download method, and (optionally) metadata.
"""

from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlparse

import aiohttp

from api.models import AnalyzeResponse, FormatInfo
from config import config
from utils import get_logger
from utils.helpers import is_known_platform, detect_media_extension, extract_filename_from_url

log = get_logger("analyzer")

_STREAM_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl": "m3u8",
    "application/x-mpegurl": "m3u8",
    "audio/mpegurl": "m3u8",
    "application/dash+xml": "mpd",
}
_VIDEO_CONTENT_PREFIX = "video/"
_AUDIO_CONTENT_PREFIX = "audio/"


class URLAnalyzer:
    """Stateless analyser — safe to reuse across requests."""

    async def analyze(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        cookies: str | None = None,
    ) -> AnalyzeResponse:
        ext = detect_media_extension(url)

        # ── 1.  Known platform → always yt-dlp ──────────────────────
        if is_known_platform(url):
            platform = self._platform_name(url)
            log.info("Known platform detected: %s", platform)
            info = await self._ytdlp_info(url, cookies)
            return AnalyzeResponse(
                url=url,
                media_type=ext or info.get("ext", "unknown"),
                recommended_method="ytdlp",
                title=info.get("title"),
                filesize=info.get("filesize") or info.get("filesize_approx"),
                formats=self._extract_formats(info),
                is_playlist=info.get("_type") == "playlist",
                platform=platform,
            )

        # ── 2.  Streaming manifest (.m3u8 / .mpd) → yt-dlp ─────────
        if ext in ("m3u8", "mpd"):
            log.info("Streaming manifest detected: .%s", ext)
            return AnalyzeResponse(
                url=url,
                media_type=ext,
                recommended_method="ytdlp",
                title=extract_filename_from_url(url),
            )

        # ── 3.  Direct media file → aria2 / direct ──────────────────
        if ext in ("mp4", "webm", "mkv", "avi", "mov", "flv", "mp3", "m4a", "ogg", "wav", "aac"):
            head = await self._head_request(url, headers)
            size = head.get("size")
            method = "aria2" if self._aria2_available() else "direct"
            media_type = ext if ext in ("mp3", "m4a", "ogg", "wav", "aac") and "audio" or ext
            return AnalyzeResponse(
                url=url,
                media_type=ext,
                recommended_method=method,
                title=extract_filename_from_url(url),
                filesize=size,
            )

        # ── 4.  Probe with HEAD request ─────────────────────────────
        head = await self._head_request(url, headers)
        ct = head.get("content_type", "")
        size = head.get("size")

        if ct in _STREAM_CONTENT_TYPES:
            return AnalyzeResponse(
                url=url,
                media_type=_STREAM_CONTENT_TYPES[ct],
                recommended_method="ytdlp",
                title=extract_filename_from_url(url),
                filesize=size,
            )

        if ct.startswith(_VIDEO_CONTENT_PREFIX) or ct.startswith(_AUDIO_CONTENT_PREFIX):
            method = "aria2" if self._aria2_available() else "direct"
            mtype = ct.split("/")[-1].split(";")[0]
            return AnalyzeResponse(
                url=url,
                media_type=mtype,
                recommended_method=method,
                title=extract_filename_from_url(url),
                filesize=size,
            )

        # ── 5.  Fallback: try yt-dlp info extraction ────────────────
        log.info("Attempting yt-dlp info extraction for: %s", url)
        try:
            info = await self._ytdlp_info(url, cookies)
            return AnalyzeResponse(
                url=url,
                media_type=info.get("ext", "unknown"),
                recommended_method="ytdlp",
                title=info.get("title"),
                filesize=info.get("filesize") or info.get("filesize_approx"),
                formats=self._extract_formats(info),
                platform=self._platform_name(url),
            )
        except Exception:
            pass

        # ── 6.  Nothing matched ─────────────────────────────────────
        return AnalyzeResponse(
            url=url,
            media_type="unknown",
            recommended_method="ytdlp",
            title=extract_filename_from_url(url),
        )

    # ── private helpers ─────────────────────────────────────────────────

    @staticmethod
    async def _head_request(
        url: str, headers: dict[str, str] | None = None
    ) -> dict:
        """Return {content_type, size} via an HTTP HEAD request."""
        result: dict = {}
        try:
            req_headers = dict(headers) if headers else {}
            req_headers.setdefault(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(url, headers=req_headers, allow_redirects=True) as resp:
                    ct = resp.headers.get("Content-Type", "")
                    cl = resp.headers.get("Content-Length")
                    result["content_type"] = ct.lower().split(";")[0].strip()
                    if cl and cl.isdigit():
                        result["size"] = int(cl)
        except Exception as exc:
            log.debug("HEAD request failed for %s: %s", url, exc)
        return result

    @staticmethod
    async def _ytdlp_info(url: str, cookies: str | None = None) -> dict:
        cmd = [
            config.YTDLP_PATH,
            "--dump-json",
            "--no-download",
            "--no-warnings",
            "--no-playlist",
            url,
        ]
        if cookies:
            cmd.extend(["--add-header", f"Cookie: {cookies}"])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip()[:300])
        return json.loads(stdout.decode(errors="replace"))

    @staticmethod
    def _extract_formats(info: dict) -> list[FormatInfo]:
        raw = info.get("formats") or []
        out: list[FormatInfo] = []
        for f in raw[-20:]:  # limit to last 20 (usually best quality near end)
            out.append(
                FormatInfo(
                    format_id=str(f.get("format_id", "")),
                    ext=f.get("ext", "?"),
                    resolution=f.get("resolution") or f.get("format_note", ""),
                    filesize=f.get("filesize") or f.get("filesize_approx"),
                    note=f.get("format_note", ""),
                )
            )
        return out

    @staticmethod
    def _platform_name(url: str) -> str:
        host = urlparse(url).hostname or ""
        host = re.sub(r"^(www\.|m\.)", "", host)
        return host.split(".")[0].capitalize()

    @staticmethod
    def _aria2_available() -> bool:
        import shutil
        return shutil.which(config.ARIA2C_PATH) is not None