"""Generic HTML page extractor.

Looks for the usual places a page exposes a playable stream: ``<video>`` and
``<source>`` tags, Open Graph / Twitter meta tags, JSON-LD ``contentUrl`` and
bare ``.m3u8`` / ``.mpd`` / media URLs in inline scripts.
"""

from __future__ import annotations

import html
import json
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from ..http import HttpClient, guess_ext_from_url, looks_like_url
from ..models import Format, MediaInfo
from .base import Extractor

_VIDEO_SRC = re.compile(r"<video[^>]+src=[\"']([^\"']+)[\"']", re.I)
_SOURCE_SRC = re.compile(r"<source[^>]+src=[\"']([^\"']+)[\"']", re.I)
_META = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']([^\"']+)[\"'][^>]+content=[\"']([^\"']+)[\"']",
    re.I,
)
_JSONLD = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)
_MANIFEST = re.compile(r"https?://[^\s\"'<>]+?\.(?:m3u8|mpd)(?:\?[^\s\"'<>]*)?", re.I)
_MEDIA_URL = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:mp4|webm|m4a|mp3|aac)(?:\?[^\s\"'<>]*)?", re.I
)


class GenericExtractor(Extractor):
    name = "generic"
    priority = -100

    def matches(self, url: str) -> bool:
        return True

    def extract(self, url, client: HttpClient, headers: Optional[Dict[str, str]] = None) -> MediaInfo:
        headers = headers or {}
        response = client.get(url, headers=headers)
        text = response.body.decode("utf-8", "replace")
        final_url = response.url or url

        candidates: List[str] = []
        for regex in (_VIDEO_SRC, _SOURCE_SRC):
            candidates.extend(regex.findall(text))
        for name, content in _META.findall(text):
            key = name.lower()
            if key in {"og:video", "og:video:url", "og:video:secure_url",
                       "twitter:player:stream", "twitter:player:stream:content_type"}:
                candidates.append(content)
        candidates.extend(self._from_jsonld(text))
        candidates.extend(_MANIFEST.findall(text))
        candidates.extend(_MEDIA_URL.findall(text))

        seen = set()
        ordered: List[str] = []
        for cand in candidates:
            cand = html.unescape(cand.strip())
            if not cand:
                continue
            absolute = urljoin(final_url, cand)
            if not looks_like_url(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            ordered.append(absolute)

        formats: List[Format] = []
        for index, media_url in enumerate(ordered[:20]):
            path = media_url.split("?", 1)[0].lower()
            if path.endswith(".m3u8"):
                protocol, ext = "hls", "mp4"
            elif path.endswith(".mpd"):
                protocol, ext = "dash", "mp4"
            else:
                protocol = "http"
                ext = guess_ext_from_url(media_url)
            formats.append(
                Format(format_id=f"auto-{index}", url=media_url, protocol=protocol, ext=ext)
            )

        if not formats:
            formats.append(Format(format_id="page", url=final_url, protocol="http", ext="mp4"))

        title = self._title(text) or "download"
        return MediaInfo(
            title=title,
            formats=formats,
            url=final_url,
            extractor=self.name,
            thumbnail=self._meta(text, "og:image"),
            description=self._meta(text, "og:description"),
            http_headers=headers,
        )

    def _from_jsonld(self, text: str) -> List[str]:
        urls: List[str] = []
        for block in _JSONLD.findall(text):
            try:
                data = json.loads(block.strip())
            except ValueError:
                continue
            for item in _walk(data):
                if isinstance(item, dict):
                    for key in ("contentUrl", "embedUrl", "url"):
                        value = item.get(key)
                        if isinstance(value, str) and looks_like_url(value):
                            urls.append(value)
        return urls

    def _title(self, text: str) -> Optional[str]:
        value = self._meta(text, "og:title") or self._meta(text, "twitter:title")
        if value:
            return html.unescape(value)
        match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        if match:
            return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
        return None

    def _meta(self, text: str, prop: str) -> Optional[str]:
        for name, content in _META.findall(text):
            if name.lower() == prop.lower():
                return content
        return None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


__all__ = ["GenericExtractor"]
