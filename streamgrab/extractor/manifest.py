"""Extractors for direct media URLs and manifest URLs."""

from __future__ import annotations

import os
import urllib.parse
from typing import Dict, Optional

from ..http import HttpClient, guess_ext_from_url
from ..models import Format, MediaInfo
from .base import Extractor


class DirectMediaExtractor(Extractor):
    """Handles URLs that point straight at a media file."""

    name = "direct"
    priority = 5

    MEDIA_EXTS = {
        "mp4", "m4v", "webm", "mkv", "mov", "flv", "avi", "ts", "m4a",
        "mp3", "aac", "ogg", "opus", "wav", "flac",
    }

    def matches(self, url: str) -> bool:
        ext = guess_ext_from_url(url, default="").lower()
        return ext in self.MEDIA_EXTS

    def extract(self, url, client: HttpClient, headers: Optional[Dict[str, str]] = None) -> MediaInfo:
        ext = guess_ext_from_url(url, default="mp4")
        audio_only = ext in {"m4a", "mp3", "aac", "ogg", "opus", "wav", "flac"}
        fmt = Format(
            format_id="direct",
            url=url,
            protocol="http",
            ext=ext,
            vcodec=None if audio_only else "unknown",
            acodec="unknown" if audio_only else None,
        )
        return MediaInfo(
            title=_title_from_url(url),
            formats=[fmt],
            url=url,
            extractor=self.name,
            http_headers=headers or {},
        )


class HlsExtractor(Extractor):
    name = "hls"
    priority = 10

    def matches(self, url: str) -> bool:
        path = urllib.parse.urlsplit(url).path.lower()
        return path.endswith(".m3u8") or path.endswith(".m3u")

    def extract(self, url, client: HttpClient, headers: Optional[Dict[str, str]] = None) -> MediaInfo:
        from .. import hls

        playlist = hls.fetch_playlist(client, url, headers=headers)
        formats = []
        if playlist.is_master:
            for index, variant in enumerate(playlist.variants):
                width = variant.resolution[0] if variant.resolution else None
                height = variant.resolution[1] if variant.resolution else None
                formats.append(
                    Format(
                        format_id=f"hls-{index}",
                        url=variant.uri,
                        protocol="hls",
                        ext="mp4",
                        vcodec=variant.codecs,
                        width=width,
                        height=height,
                        fps=variant.frame_rate,
                        tbr=(variant.bandwidth / 1000.0) if variant.bandwidth else None,
                    )
                )
        else:
            formats.append(
                Format(
                    format_id="hls",
                    url=url,
                    protocol="hls",
                    ext="mp4",
                    vcodec="unknown",
                    acodec="unknown",
                )
            )
        return MediaInfo(
            title=_title_from_url(url),
            formats=formats,
            url=url,
            extractor=self.name,
            http_headers=headers or {},
        )


class DashExtractor(Extractor):
    name = "dash"
    priority = 10

    def matches(self, url: str) -> bool:
        path = urllib.parse.urlsplit(url).path.lower()
        return path.endswith(".mpd")

    def extract(self, url, client: HttpClient, headers: Optional[Dict[str, str]] = None) -> MediaInfo:
        from .. import dash

        manifest = dash.fetch_manifest(client, url, headers=headers)
        formats = []
        for rep in manifest.video:
            formats.append(
                Format(
                    format_id=rep.id,
                    url=url,
                    protocol="dash",
                    ext="mp4",
                    vcodec=rep.codecs,
                    width=rep.width,
                    height=rep.height,
                    tbr=(rep.bandwidth / 1000.0) if rep.bandwidth else None,
                )
            )
        for rep in manifest.audio:
            formats.append(
                Format(
                    format_id=rep.id,
                    url=url,
                    protocol="dash",
                    ext="m4a",
                    acodec=rep.codecs,
                    abr=(rep.bandwidth / 1000.0) if rep.bandwidth else None,
                )
            )
        if not formats:
            formats.append(Format(format_id="dash", url=url, protocol="dash"))
        info = MediaInfo(
            title=_title_from_url(url),
            formats=formats,
            url=url,
            extractor=self.name,
            duration=manifest.duration,
            http_headers=headers or {},
        )
        info.extra["manifest"] = manifest
        return info


def _title_from_url(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem or "download"


__all__ = ["DirectMediaExtractor", "HlsExtractor", "DashExtractor"]
