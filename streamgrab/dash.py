"""MPEG-DASH (``.mpd``) parsing and downloading.

Supports ``SegmentTemplate`` (with ``SegmentTimeline``), ``SegmentList`` and
``SegmentBase`` addressing, ``BaseURL`` resolution, and separate audio/video
representations that are muxed afterwards.
"""

from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .http import HttpClient, absolutize
from .util import Log, coerce_int, parse_iso8601_duration

SegmentProgress = Callable[[int, int], None]


@dataclass
class DashSegment:
    url: str
    byte_range: Optional[Tuple[int, int]] = None  # (offset, length)


@dataclass
class DashRepresentation:
    id: str
    mime_type: str = ""
    codecs: str = ""
    bandwidth: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    init: Optional[DashSegment] = None
    segments: List[DashSegment] = field(default_factory=list)

    @property
    def is_video(self) -> bool:
        return self.mime_type.startswith("video") or bool(self.height)

    @property
    def is_audio(self) -> bool:
        return self.mime_type.startswith("audio") or (
            not self.height and "audio" in self.codecs.lower()
        )


@dataclass
class DashManifest:
    base_url: str
    duration: Optional[float] = None
    video: List[DashRepresentation] = field(default_factory=list)
    audio: List[DashRepresentation] = field(default_factory=list)

    def best_video(self) -> Optional[DashRepresentation]:
        if not self.video:
            return None
        return max(self.video, key=lambda r: ((r.height or 0), (r.bandwidth or 0)))

    def best_audio(self) -> Optional[DashRepresentation]:
        if not self.audio:
            return None
        return max(self.audio, key=lambda r: (r.bandwidth or 0))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_all(element: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in element.iter() if _local(child.tag) == name]


def _first(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None or element.text is None:
        return None
    return element.text.strip()


def parse_mpd(xml_text: str, base_url: str) -> DashManifest:
    root = ET.fromstring(xml_text)
    manifest = DashManifest(base_url=base_url)
    manifest.duration = parse_iso8601_duration(root.get("mediaPresentationDuration"))

    mpd_base = _text(_first(root, "BaseURL"))
    if mpd_base:
        base_url = absolutize(base_url, mpd_base)
        manifest.base_url = base_url

    periods = [child for child in root if _local(child.tag) == "Period"]
    if not periods:
        periods = [root]

    for period in periods:
        period_duration = parse_iso8601_duration(period.get("duration")) or manifest.duration
        period_base = _text(_first(period, "BaseURL"))
        p_base = absolutize(base_url, period_base) if period_base else base_url

        adaptation_sets = [c for c in period if _local(c.tag) == "AdaptationSet"]
        for adaptation in adaptation_sets:
            as_base = _text(_first(adaptation, "BaseURL"))
            a_base = absolutize(p_base, as_base) if as_base else p_base
            as_mime = adaptation.get("mimeType", "")
            as_content = adaptation.get("contentType", "")

            for rep in [c for c in adaptation if _local(c.tag) == "Representation"]:
                rep_base = _text(_first(rep, "BaseURL"))
                r_base = absolutize(a_base, rep_base) if rep_base else a_base
                mime = rep.get("mimeType") or as_mime
                if not mime:
                    if as_content:
                        mime = as_content + "/"
                rep_id = rep.get("id", "0")

                representation = DashRepresentation(
                    id=rep_id,
                    mime_type=mime,
                    codecs=rep.get("codecs") or adaptation.get("codecs", ""),
                    bandwidth=coerce_int(rep.get("bandwidth") or adaptation.get("bandwidth")),
                    width=coerce_int(rep.get("width") or adaptation.get("width")),
                    height=coerce_int(rep.get("height") or adaptation.get("height")),
                )

                template = _pick_child(rep, adaptation, "SegmentTemplate")
                seg_list = _pick_child(rep, adaptation, "SegmentList")
                seg_base = _pick_child(rep, adaptation, "SegmentBase")

                if template is not None:
                    _apply_template(representation, template, r_base, rep_id, period_duration)
                elif seg_list is not None:
                    _apply_segment_list(representation, seg_list, r_base)
                elif seg_base is not None:
                    _apply_segment_base(representation, seg_base, r_base)
                else:
                    representation.segments.append(DashSegment(url=r_base))

                if representation.is_audio:
                    manifest.audio.append(representation)
                else:
                    manifest.video.append(representation)

    return manifest


def _pick_child(rep: ET.Element, adaptation: ET.Element, name: str) -> Optional[ET.Element]:
    element = _first(rep, name)
    if element is None:
        element = _first(adaptation, name)
    return element


def _apply_template(
    rep: DashRepresentation,
    template: ET.Element,
    base: str,
    rep_id: str,
    period_duration: Optional[float],
) -> None:
    media_tpl = template.get("media", "")
    init_tpl = template.get("initialization")
    timescale = coerce_int(template.get("timescale")) or 1
    start_number = coerce_int(template.get("startNumber")) or 1
    duration = coerce_int(template.get("duration"))
    pto = coerce_int(template.get("presentationTimeOffset")) or 0

    if init_tpl:
        rep.init = DashSegment(
            url=absolutize(base, _fill(init_tpl, rep_id, rep.bandwidth, start_number, 0, rep))
        )

    timeline = _first(template, "SegmentTimeline")
    if timeline is not None:
        entries = [c for c in timeline if _local(c.tag) == "S"]
        number = start_number
        time_cursor = 0
        for entry in entries:
            t = coerce_int(entry.get("t"))
            if t is not None:
                time_cursor = t
            d = coerce_int(entry.get("d")) or 0
            r = coerce_int(entry.get("r")) or 0
            for _ in range(r + 1):
                rep.segments.append(
                    DashSegment(
                        url=absolutize(base, _fill(media_tpl, rep_id, rep.bandwidth, number, time_cursor, rep))
                    )
                )
                time_cursor += d
                number += 1
        return

    if duration and period_duration:
        count = max(1, int(round(period_duration * timescale / duration)))
        for offset in range(count):
            number = start_number + offset
            t = pto + offset * duration
            rep.segments.append(
                DashSegment(
                    url=absolutize(base, _fill(media_tpl, rep_id, rep.bandwidth, number, t, rep))
                )
            )
        return

    # No timeline and no duration: single-file representation.
    if not rep.segments:
        rep.segments.append(
            DashSegment(
                url=absolutize(base, _fill(media_tpl, rep_id, rep.bandwidth, start_number, pto, rep))
            )
        )


def _fill(template: str, rep_id: str, bandwidth: Optional[int], number: int, time: int, rep: DashRepresentation) -> str:
    out = template
    out = out.replace("$RepresentationID$", rep_id)
    out = out.replace("$Bandwidth$", str(bandwidth or 0))
    out = out.replace("$Number$", str(number))
    out = out.replace("$Time$", str(time))
    out = out.replace("$Width$", str(rep.width or 0))
    out = out.replace("$Height$", str(rep.height or 0))
    out = out.replace("$$", "$")
    return out


def _apply_segment_list(rep: DashRepresentation, seg_list: ET.Element, base: str) -> None:
    init = _first(seg_list, "Initialization")
    if init is not None:
        source = init.get("sourceURL")
        if source:
            rep.init = DashSegment(url=absolutize(base, source), byte_range=_parse_range(init.get("range")))
    for seg in [c for c in seg_list if _local(c.tag) == "SegmentURL"]:
        media = seg.get("media")
        if media:
            rep.segments.append(
                DashSegment(url=absolutize(base, media), byte_range=_parse_range(seg.get("mediaRange")))
            )


def _apply_segment_base(rep: DashRepresentation, seg_base: ET.Element, base: str) -> None:
    init = _first(seg_base, "Initialization")
    if init is not None and init.get("range"):
        rep.init = DashSegment(url=base, byte_range=_parse_range(init.get("range")))
    rep.segments.append(DashSegment(url=base))


def _parse_range(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    if "-" in value:
        start_s, end_s = value.split("-", 1)
        try:
            start = int(start_s)
            end = int(end_s)
            return start, end - start + 1
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def fetch_manifest(client: HttpClient, url: str, headers: Optional[Dict[str, str]] = None) -> DashManifest:
    text = client.get_text(url, headers=headers)
    return parse_mpd(text, url)


def download_dash(
    client: HttpClient,
    url_or_manifest,
    dest: str,
    headers: Optional[Dict[str, str]] = None,
    jobs: int = 8,
    progress: Optional[SegmentProgress] = None,
    log: Optional[Log] = None,
    mux: bool = True,
    video_id: Optional[str] = None,
    audio_id: Optional[str] = None,
) -> List[str]:
    log = log or Log("warn")
    headers = headers or {}

    if isinstance(url_or_manifest, DashManifest):
        manifest = url_or_manifest
    else:
        manifest = fetch_manifest(client, url_or_manifest, headers=headers)

    video = _pick(manifest.video, video_id) or manifest.best_video()
    audio = _pick(manifest.audio, audio_id) or manifest.best_audio()
    if video is None and audio is None:
        raise ValueError("manifest has no usable representations")

    base, _ = os.path.splitext(dest)
    outputs: List[str] = []

    video_path = None
    if video is not None:
        video_path = base + ".video.mp4"
        _download_representation(client, video, video_path, headers, jobs, progress, log)
        outputs.append(video_path)

    audio_path = None
    if audio is not None:
        audio_path = base + ".audio.m4a"
        _download_representation(client, audio, audio_path, headers, jobs, progress, log)

    if mux and video_path and audio_path:
        from . import muxer

        if muxer.has_ffmpeg():
            final = base + ".mp4"
            if muxer.mux(video_path, audio_path, final, log=log):
                for tmp in (video_path, audio_path):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return [final]
        else:
            log.warn("ffmpeg not found; keeping separate video/audio files")
            outputs.append(audio_path)
            return outputs

    if audio_path and not video_path:
        outputs.append(audio_path)
    return outputs


def _pick(reps: List[DashRepresentation], rep_id: Optional[str]) -> Optional[DashRepresentation]:
    if not rep_id:
        return None
    for rep in reps:
        if rep.id == rep_id:
            return rep
    return None


def _download_representation(
    client: HttpClient,
    rep: DashRepresentation,
    out_path: str,
    headers: Dict[str, str],
    jobs: int,
    progress: Optional[SegmentProgress],
    log: Log,
) -> str:
    work_dir = out_path + ".sgdash"
    os.makedirs(work_dir, exist_ok=True)
    files: List[str] = []

    if rep.init:
        init_path = os.path.join(work_dir, "init")
        _fetch_to_file(client, rep.init, init_path, headers, log)
        files.append(init_path)

    total = len(rep.segments)
    done = 0
    results: Dict[int, str] = {}

    def work(index: int, segment: DashSegment) -> str:
        path = os.path.join(work_dir, f"{index:06d}.part")
        _fetch_to_file(client, segment, path, headers, log)
        return path

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(work, i, s): i for i, s in enumerate(rep.segments)}
        for fut in as_completed(futures):
            index = futures[fut]
            results[index] = fut.result()
            done += 1
            if progress:
                progress(done, total)

    for i in range(total):
        files.append(results[i])

    with open(out_path, "wb") as out:
        for path in files:
            with open(path, "rb") as fh:
                shutil.copyfileobj(fh, out, 1 << 20)

    shutil.rmtree(work_dir, ignore_errors=True)
    return out_path


def _fetch_to_file(
    client: HttpClient,
    segment: DashSegment,
    path: str,
    headers: Dict[str, str],
    log: Log,
) -> None:
    rng = None
    if segment.byte_range is not None:
        offset, length = segment.byte_range
        rng = f"bytes={offset}-{offset + length - 1}"
    with open(path, "wb") as fh:
        fh.write(client.get(segment.url, headers=headers, byte_range=rng).body)


__all__ = [
    "DashManifest",
    "DashRepresentation",
    "DashSegment",
    "parse_mpd",
    "fetch_manifest",
    "download_dash",
]
