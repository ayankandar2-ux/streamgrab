"""Example third-party extractor plugin.

Drop a module like this on ``PYTHONPATH`` and register it with an
``streamgrab.extractors`` entry point, or pass it explicitly:

    from streamgrab import Engine
    from streamgrab.extractor import default_extractors
    from myplugin import ExampleExtractor

    engine = Engine(extractors=[ExampleExtractor(), *default_extractors()])
"""

from __future__ import annotations

import urllib.parse
from typing import Dict, Optional

from streamgrab.extractor import Extractor
from streamgrab.http import HttpClient
from streamgrab.models import Format, MediaInfo


class ExampleExtractor(Extractor):
    """Recognises ``https://media.example.com/watch/<id>`` and returns a fake
    set of renditions. Replace ``extract`` with a real API call.
    """

    name = "example"
    priority = 50

    def matches(self, url: str) -> bool:
        return urllib.parse.urlsplit(url).netloc == "media.example.com"

    def extract(
        self,
        url: str,
        client: HttpClient,
        headers: Optional[Dict[str, str]] = None,
    ) -> MediaInfo:
        video_id = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        # In a real plugin you would call the site's API here.
        base = f"https://cdn.example.com/{video_id}"
        formats = [
            Format(format_id="720", url=f"{base}/720.m3u8", protocol="hls",
                   height=720, ext="mp4"),
            Format(format_id="360", url=f"{base}/360.m3u8", protocol="hls",
                   height=360, ext="mp4"),
            Format(format_id="audio", url=f"{base}/audio.m4a", protocol="http",
                   acodec="mp4a", ext="m4a"),
        ]
        return MediaInfo(
            title=f"Example {video_id}",
            formats=formats,
            url=url,
            extractor=self.name,
            http_headers=headers or {},
        )
