"""
Utility helpers shared across modules.
"""

import re
import math
from urllib.parse import urlparse, unquote


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Remove or replace characters that are illegal in filenames."""
    if not name:
        return "download"
    name = unquote(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"_+", "_", name).strip("_. ")
    if len(name) > max_length:
        stem, dot, ext = name.rpartition(".")
        if dot:
            name = stem[: max_length - len(ext) - 1] + "." + ext
        else:
            name = name[:max_length]
    return name or "download"


def extract_filename_from_url(url: str) -> str:
    """Best-effort filename extraction from a URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        segment = path.split("/")[-1]
        if "." in segment:
            return sanitize_filename(segment)
    return sanitize_filename(parsed.netloc.replace(".", "_"))


def format_bytes(num_bytes: int | float) -> str:
    if num_bytes == 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(max(num_bytes, 1), 1024)))
    i = min(i, len(units) - 1)
    value = num_bytes / (1024 ** i)
    return f"{value:.1f} {units[i]}"


_KNOWN_VIDEO_PLATFORMS: list[re.Pattern] = [
    re.compile(r"(youtube\.com|youtu\.be)", re.I),
    re.compile(r"vimeo\.com", re.I),
    re.compile(r"dailymotion\.com", re.I),
    re.compile(r"twitch\.tv", re.I),
    re.compile(r"facebook\.com.*/video", re.I),
    re.compile(r"twitter\.com|x\.com", re.I),
    re.compile(r"instagram\.com", re.I),
    re.compile(r"tiktok\.com", re.I),
    re.compile(r"bilibili\.com", re.I),
    re.compile(r"reddit\.com", re.I),
    re.compile(r"streamable\.com", re.I),
    re.compile(r"soundcloud\.com", re.I),
]


def is_known_platform(url: str) -> bool:
    return any(p.search(url) for p in _KNOWN_VIDEO_PLATFORMS)


def detect_media_extension(url: str) -> str | None:
    """Return the media extension found in the URL path (without dot), or None."""
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    for ext in ("mp4", "webm", "mkv", "avi", "mov", "flv", "m3u8", "mpd", "mp3", "m4a", "ogg", "wav", "aac", "ts"):
        if path_lower.endswith(f".{ext}"):
            return ext
    return None