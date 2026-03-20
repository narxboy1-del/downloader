"""
Smart routing: given analysis results and system capabilities, pick the
optimal downloader for a URL.
"""

from __future__ import annotations
import shutil

from config import config
from utils import get_logger

log = get_logger("router")


def select_method(
    url: str,
    media_type: str,
    requested_method: str | None = None,
) -> str:
    """
    Return one of: 'ytdlp', 'aria2', 'direct'.

    Priority:
      1. Explicit request from caller (if tool available)
      2. Streaming / complex → yt-dlp
      3. Direct file → aria2 (fallback to direct)
    """
    ytdlp_ok = shutil.which(config.YTDLP_PATH) is not None
    aria2_ok = shutil.which(config.ARIA2C_PATH) is not None

    # Honour explicit choice if possible
    if requested_method:
        m = requested_method.lower()
        if m == "ytdlp" and ytdlp_ok:
            return "ytdlp"
        if m == "aria2" and aria2_ok:
            return "aria2"
        if m == "direct":
            return "direct"
        log.warning("Requested method '%s' unavailable, auto-selecting.", requested_method)

    # Streaming manifests → yt-dlp
    if media_type in ("m3u8", "mpd"):
        if ytdlp_ok:
            return "ytdlp"
        return "direct"  # last resort

    # Page / unknown / known-platform → yt-dlp
    if media_type in ("page", "unknown") or media_type == "":
        if ytdlp_ok:
            return "ytdlp"
        return "direct"

    # Direct files → aria2 preferred, fallback direct
    if aria2_ok:
        return "aria2"
    return "direct"