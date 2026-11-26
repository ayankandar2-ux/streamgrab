"""Tests for DASH MPD parsing."""

from streamgrab.dash import parse_mpd

TEMPLATE_MPD = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="PT10S">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <SegmentTemplate initialization="$RepresentationID$/init.mp4"
                       media="$RepresentationID$/seg-$Number$.m4s"
                       startNumber="1" duration="2" timescale="1"/>
      <Representation id="v1" bandwidth="1000000" width="1280" height="720" codecs="avc1.4d401f"/>
      <Representation id="v0" bandwidth="300000" width="640" height="360" codecs="avc1.4d401e"/>
    </AdaptationSet>
    <AdaptationSet mimeType="audio/mp4">
      <SegmentTemplate initialization="$RepresentationID$/init.mp4"
                       media="$RepresentationID$/seg-$Number$.m4s"
                       startNumber="1" duration="2" timescale="1"/>
      <Representation id="a1" bandwidth="128000" codecs="mp4a.40.2"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

TIMELINE_MPD = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <SegmentTemplate media="chunk-$Number$.m4s" startNumber="5" timescale="90000">
        <SegmentTimeline>
          <S t="0" d="180000" r="2"/>
        </SegmentTimeline>
      </SegmentTemplate>
      <Representation id="v" bandwidth="500000" width="1280" height="720" codecs="avc1"/>
    </AdaptationSet>
  </Period>
</MPD>
"""


def test_template_representation_and_segments():
    manifest = parse_mpd(TEMPLATE_MPD, "https://cdn.example.com/manifest.mpd")
    assert len(manifest.video) == 2
    assert len(manifest.audio) == 1
    best = manifest.best_video()
    assert best is not None
    assert best.height == 720
    assert best.id == "v1"
    assert best.init is not None
    assert best.init.url == "https://cdn.example.com/v1/init.mp4"
    assert len(best.segments) == 5
    assert best.segments[0].url == "https://cdn.example.com/v1/seg-1.m4s"
    assert best.segments[-1].url == "https://cdn.example.com/v1/seg-5.m4s"


def test_segment_timeline():
    manifest = parse_mpd(TIMELINE_MPD, "https://cdn.example.com/manifest.mpd")
    video = manifest.video[0]
    assert len(video.segments) == 3
    assert video.segments[0].url == "https://cdn.example.com/chunk-5.m4s"
    assert video.segments[1].url == "https://cdn.example.com/chunk-6.m4s"
    assert video.segments[2].url == "https://cdn.example.com/chunk-7.m4s"


def test_segment_list():
    mpd = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <Representation id="v" bandwidth="1" width="2" height="2" codecs="avc1">
        <SegmentList>
          <Initialization sourceURL="init.mp4"/>
          <SegmentURL media="a.m4s"/>
          <SegmentURL media="b.m4s" mediaRange="0-99"/>
        </SegmentList>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""
    manifest = parse_mpd(mpd, "https://cdn.example.com/m.mpd")
    rep = manifest.video[0]
    assert rep.init is not None
    assert rep.init.url == "https://cdn.example.com/init.mp4"
    assert [s.url for s in rep.segments] == [
        "https://cdn.example.com/a.m4s",
        "https://cdn.example.com/b.m4s",
    ]
    assert rep.segments[1].byte_range == (0, 100)
