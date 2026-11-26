"""Data models shared across extractors and the download engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Format:
    """A single downloadable rendition.

    ``protocol`` is one of ``http``, ``hls`` or ``dash``. For adaptive
    protocols the rendition may be muxed (``url`` only) or split into a
    separate video and audio stream (``url`` + ``audio_url``).
    """

    format_id: str
    url: str
    protocol: str = "http"
    ext: str = "mp4"
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    tbr: Optional[float] = None
    abr: Optional[float] = None
    filesize: Optional[int] = None
    audio_url: Optional[str] = None
    http_headers: Dict[str, str] = field(default_factory=dict)
    note: Optional[str] = None

    @property
    def is_audio_only(self) -> bool:
        return self.vcodec in (None, "none") and self.acodec not in (None, "none")

    @property
    def is_video_only(self) -> bool:
        return self.acodec in (None, "none") and self.vcodec not in (None, "none")

    def label(self) -> str:
        bits: List[str] = [self.format_id]
        if self.width and self.height:
            bits.append(f"{self.width}x{self.height}")
        if self.height:
            bits.append(f"{self.height}p")
        if self.fps:
            bits.append(f"{self.fps:g}fps")
        if self.vcodec:
            bits.append(f"v:{self.vcodec}")
        if self.acodec:
            bits.append(f"a:{self.acodec}")
        if self.tbr:
            bits.append(f"{self.tbr:.0f}k")
        bits.append(self.protocol)
        return "  ".join(bits)


@dataclass
class MediaInfo:
    """Result of extracting a page or manifest URL."""

    title: str
    formats: List[Format]
    url: str = ""
    extractor: str = "generic"
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    http_headers: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, object] = field(default_factory=dict)

    def best(self, prefer_audio: bool = False) -> Optional[Format]:
        if not self.formats:
            return None
        if prefer_audio:
            audio = [f for f in self.formats if f.is_audio_only]
            pool = audio or self.formats
            return max(pool, key=lambda f: (f.abr or 0, f.tbr or 0, f.filesize or 0))
        video = [f for f in self.formats if not f.is_audio_only]
        pool = video or self.formats
        return max(
            pool,
            key=lambda f: (
                (f.height or 0),
                (f.fps or 0),
                (f.tbr or 0),
                (f.filesize or 0),
            ),
        )
