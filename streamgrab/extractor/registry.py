"""Extractor registry and resolution."""

from __future__ import annotations

from typing import List, Optional

from ..http import HttpClient
from ..models import MediaInfo
from .base import Extractor
from .generic import GenericExtractor
from .manifest import DashExtractor, DirectMediaExtractor, HlsExtractor
from .ytdlp_bridge import YtDlpExtractor


def default_extractors() -> List[Extractor]:
    extractors: List[Extractor] = [
        HlsExtractor(),
        DashExtractor(),
        DirectMediaExtractor(),
        YtDlpExtractor(),
        GenericExtractor(),
    ]
    extractors.sort(key=lambda e: e.priority, reverse=True)
    return extractors


def resolve(
    url: str,
    client: HttpClient,
    extractors: Optional[List[Extractor]] = None,
    headers: Optional[dict] = None,
) -> MediaInfo:
    extractors = extractors or default_extractors()
    last_error: Optional[Exception] = None
    for extractor in extractors:
        try:
            if not extractor.matches(url):
                continue
            return extractor.extract(url, client, headers=headers)
        except Exception as exc:  # try the next extractor
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError(f"no extractor matched {url}")


__all__ = ["Extractor", "default_extractors", "resolve"]
