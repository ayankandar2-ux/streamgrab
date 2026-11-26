"""Tests for HLS playlist parsing."""

from streamgrab.hls import parse_m3u8

MASTER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.4d401e,mp4a.40.2"
360/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720,FRAME-RATE=30
720/index.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:10
#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x00000000000000000000000000000001
#EXT-X-MAP:URI="init.mp4"
#EXTINF:6.0,
seg1.m4s
#EXT-X-BYTERANGE:1000@0
#EXTINF:6.0,
seg2.m4s
#EXT-X-ENDLIST
"""


def test_master_playlist():
    playlist = parse_m3u8(MASTER, "https://cdn.example.com/master.m3u8")
    assert playlist.is_master
    assert len(playlist.variants) == 2
    best = playlist.best_variant()
    assert best is not None
    assert best.resolution == (1280, 720)
    assert best.bandwidth == 2400000
    assert best.uri == "https://cdn.example.com/720/index.m3u8"


def test_media_playlist_key_map_and_byterange():
    playlist = parse_m3u8(MEDIA, "https://cdn.example.com/720/index.m3u8")
    assert not playlist.is_master
    assert playlist.media_sequence == 10
    assert len(playlist.segments) == 2

    first = playlist.segments[0]
    assert first.uri == "https://cdn.example.com/720/seg1.m4s"
    assert first.sequence == 10
    assert first.duration == 6.0
    assert first.key is not None
    assert first.key.method == "AES-128"
    assert first.key.uri == "https://cdn.example.com/720/key.bin"
    assert first.key.iv == b"\x00" * 15 + b"\x01"
    assert first.map_uri == "https://cdn.example.com/720/init.mp4"

    second = playlist.segments[1]
    assert second.sequence == 11
    assert second.byte_range == (0, 1000)


def test_attributes_quoted_commas():
    from streamgrab.hls import parse_attributes

    attrs = parse_attributes('BANDWIDTH=1,CODECS="avc1.4d401e,mp4a.40.2",RESOLUTION=1x1')
    assert attrs["CODECS"] == "avc1.4d401e,mp4a.40.2"
    assert attrs["BANDWIDTH"] == "1"
