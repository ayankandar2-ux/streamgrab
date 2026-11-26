"""Optional yt-dlp bridge.

If the user has ``yt-dlp`` installed, it is used as a high-coverage fallback
extractor for sites streamgrab does not implement natively. streamgrab never
ships or bundles yt-dlp; it is an optional, user-provided dependency.
"""

from __future__ import annotations

from typing import Dict, Optional

from ..http import HttpClient
from ..models import Format, MediaInfo
from .base import Extractor


def _have_ytdlp() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except Exception:
        return False


class YtDlpExtractor(Extractor):
    name = "yt-dlp"
    priority = 1

    def matches(self, url: str) -> bool:
        return _have_ytdlp()

    def extract(self, url, client: HttpClient, headers: Optional[Dict[str, str]] = None) -> MediaInfo:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for item in info.get("formats") or []:
            if not item.get("url"):
                continue
            protocol = "hls" if item.get("protocol", "").startswith("m3u8") else (
                "dash" if "dash" in item.get("protocol", "") else "http"
            )
            formats.append(
                Format(
                    format_id=str(item.get("format_id", "")),
                    url=item["url"],
                    protocol=protocol,
                    ext=item.get("ext") or "mp4",
                    vcodec=item.get("vcodec"),
                    acodec=item.get("acodec"),
                    width=item.get("width"),
                    height=item.get("height"),
                    fps=item.get("fps"),
                    tbr=item.get("tbr"),
                    abr=item.get("abr"),
                    filesize=item.get("filesize") or item.get("filesize_approx"),
                    http_headers=item.get("http_headers") or {},
                    note=item.get("format_note"),
                )
            )

        return MediaInfo(
            title=info.get("title") or "download",
            formats=formats,
            url=url,
            extractor=self.name,
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            description=info.get("description"),
            http_headers=headers or {},
        )


__all__ = ["YtDlpExtractor"]
