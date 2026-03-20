"""
Abstract base class for every downloader backend.
"""

from __future__ import annotations

import abc
from pathlib import Path


class BaseDownloader(abc.ABC):
    """All downloaders expose the same two methods."""

    @abc.abstractmethod
    async def download(
        self,
        url: str,
        output_dir: Path,
        *,
        filename: str | None = None,
        headers: dict[str, str] | None = None,
        cookies: str | None = None,
        format_id: str | None = None,
        progress_callback=None,       # async callable(dict) | None
    ) -> Path:
        """Download *url* into *output_dir* and return the final file path."""
        ...

    @abc.abstractmethod
    async def get_name(self) -> str:
        ...