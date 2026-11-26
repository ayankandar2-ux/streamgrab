"""Extractor plugins for streamgrab."""

from .base import Extractor
from .generic import GenericExtractor
from .manifest import DashExtractor, DirectMediaExtractor, HlsExtractor
from .registry import default_extractors, resolve
from .ytdlp_bridge import YtDlpExtractor

__all__ = [
    "Extractor",
    "GenericExtractor",
    "HlsExtractor",
    "DashExtractor",
    "DirectMediaExtractor",
    "YtDlpExtractor",
    "default_extractors",
    "resolve",
]
