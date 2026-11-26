"""Tests for extractors and format selection."""

from streamgrab.engine import Engine
from streamgrab.extractor.generic import GenericExtractor
from streamgrab.extractor.manifest import DirectMediaExtractor, HlsExtractor
from streamgrab.http import HttpResponse
from streamgrab.models import Format, MediaInfo

HTML = """<html><head>
<title>My Clip</title>
<meta property="og:title" content="My Clip"/>
<meta property="og:video" content="https://cdn.example.com/v/clip.mp4"/>
</head><body>
<video src="/media/alt.mp4"></video>
<script>var src = "https://cdn.example.com/live/stream.m3u8";</script>
</body></html>"""


class FakeClient:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url, headers=None, byte_range=None):
        return HttpResponse(200, {"content-type": "text/html"}, self.body, url)


def test_generic_extractor_finds_media():
    media = GenericExtractor().extract("https://example.com/page", FakeClient(HTML.encode()))
    assert media.title == "My Clip"
    urls = [f.url for f in media.formats]
    assert "https://cdn.example.com/v/clip.mp4" in urls
    assert "https://example.com/media/alt.mp4" in urls
    assert "https://cdn.example.com/live/stream.m3u8" in urls


def test_manifest_extractor_matching():
    assert HlsExtractor().matches("https://x/y/index.m3u8")
    assert not HlsExtractor().matches("https://x/y/index.mp4")
    assert DirectMediaExtractor().matches("https://x/y/a.mp4")
    assert not DirectMediaExtractor().matches("https://x/y/page")


def test_direct_media_format():
    media = DirectMediaExtractor().extract("https://x/y/a.mp4", FakeClient(b""))
    assert len(media.formats) == 1
    assert media.formats[0].protocol == "http"
    assert media.formats[0].ext == "mp4"


def _media():
    return MediaInfo(
        title="t",
        formats=[
            Format(format_id="a", url="u", height=360, tbr=500),
            Format(format_id="b", url="u", height=1080, tbr=4000),
            Format(format_id="c", url="u", acodec="mp4a", abr=128),
        ],
    )


def test_select_best_and_audio():
    eng = Engine(log_level="error")
    assert eng.select(_media(), "best").format_id == "b"
    assert eng.select(_media(), "bestaudio").format_id == "c"
    assert eng.select(_media(), "a").format_id == "a"
    assert eng.select(_media(), "1080").format_id == "b"


def test_select_unknown_raises():
    eng = Engine(log_level="error")
    try:
        eng.select(_media(), "nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
