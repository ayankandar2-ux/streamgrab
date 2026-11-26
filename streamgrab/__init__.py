"""streamgrab - a modular media download engine.

Public surface::

    from streamgrab import Engine
    eng = Engine()
    info = eng.resolve("https://example.com/video.m3u8")
    files = eng.download(info, selector="best")

Everything here is original code. It implements the same *ideas* used by
production mobile downloaders (segmented HTTP, HLS, DASH, FFmpeg muxing)
without copying any vendor implementation.
"""

from .engine import Engine, MediaInfo, Format
from .http import HttpClient
from . import hls, dash, muxer, downloader

__all__ = [
    "Engine",
    "MediaInfo",
    "Format",
    "HttpClient",
    "hls",
    "dash",
    "muxer",
    "downloader",
]

__version__ = "0.1.0"
