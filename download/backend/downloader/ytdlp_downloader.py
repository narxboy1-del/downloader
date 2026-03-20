"""
yt-dlp subprocess downloader with real-time progress parsing.
Handles YouTube-like sites, HLS, DASH, and most video platforms.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from config import config
from downloader.base import BaseDownloader
from utils import get_logger

log = get_logger("ytdlp")

_RE_PROGRESS = re.compile(
    r"\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+\S+)"
)
_RE_SPEED = re.compile(r"at\s+([\d.]+\s*\S+/s)")
_RE_ETA = re.compile(r"ETA\s+(\S+)")
_RE_DEST = re.compile(r"\[download\]\s+Destination:\s+(.+)")
_RE_ALREADY = re.compile(r"\[download\]\s+(.+) has already been downloaded")
_RE_MERGE = re.compile(r"\[Merger\]\s+Merging formats into \"(.+)\"")


class YtdlpDownloader(BaseDownloader):
    async def get_name(self) -> str:
        return "ytdlp"

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

        if filename:
            output_template = str(output_dir / filename)
        else:
            output_template = str(output_dir / "%(title)s.%(ext)s")

        cmd: list[str] = [
            config.YTDLP_PATH,
            "--newline",
            "--no-color",
            "--no-overwrites",
            "-o", output_template,
            url,
        ]
        if format_id:
            cmd.extend(["-f", format_id])
        if cookies:
            cmd.extend(["--add-header", f"Cookie: {cookies}"])
        if headers:
            for k, v in headers.items():
                cmd.extend(["--add-header", f"{k}: {v}"])

        log.info("Running: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        final_path: str | None = None
        stderr_lines: list[str] = []

        async def _read_stderr():
            nonlocal final_path
            assert proc.stderr is not None
            async for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                stderr_lines.append(line)
                log.debug("[yt-dlp] %s", line)

                # Progress %
                m = _RE_PROGRESS.search(line)
                if m and progress_callback:
                    data: dict = {"progress": float(m.group(1))}
                    sm = _RE_SPEED.search(line)
                    if sm:
                        data["speed"] = sm.group(1)
                    em = _RE_ETA.search(line)
                    if em:
                        data["eta"] = em.group(1)
                    await progress_callback(data)

                # Destination
                dm = _RE_DEST.search(line)
                if dm:
                    final_path = dm.group(1).strip()
                    if progress_callback:
                        await progress_callback({"filename": os.path.basename(final_path)})

                # Already downloaded
                am = _RE_ALREADY.search(line)
                if am:
                    final_path = am.group(1).strip()

                # Merger output
                mm = _RE_MERGE.search(line)
                if mm:
                    final_path = mm.group(1).strip()

        async def _read_stdout():
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    log.debug("[yt-dlp:out] %s", line)

        await asyncio.gather(_read_stderr(), _read_stdout())
        retcode = await proc.wait()

        if retcode != 0:
            tail = "\n".join(stderr_lines[-5:])
            raise RuntimeError(f"yt-dlp exited with code {retcode}:\n{tail}")

        if final_path and os.path.isfile(final_path):
            return Path(final_path)

        # Fallback: find newest file in output_dir
        files = sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]

        raise FileNotFoundError("yt-dlp reported success but no output file found")