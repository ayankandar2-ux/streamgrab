"""HLS (``.m3u8``) parsing and downloading.

Implements master/media playlist parsing, ``EXT-X-KEY`` AES-128 decryption,
``EXT-X-MAP`` initialization segments, byte-range segments and discontinuity
handling. Segments are fetched concurrently and concatenated in order.
"""

from __future__ import annotations

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import crypto
from .http import HttpClient, absolutize
from .util import Log

SegmentProgress = Callable[[int, int], None]


@dataclass
class HlsKey:
    method: str
    uri: Optional[str] = None
    iv: Optional[bytes] = None
    keyformat: Optional[str] = None


@dataclass
class HlsSegment:
    uri: str
    duration: float = 0.0
    sequence: int = 0
    byte_range: Optional[Tuple[int, int]] = None  # (offset, length)
    key: Optional[HlsKey] = None
    map_uri: Optional[str] = None
    map_range: Optional[Tuple[int, int]] = None
    discontinuity: bool = False


@dataclass
class HlsVariant:
    uri: str
    bandwidth: Optional[int] = None
    average_bandwidth: Optional[int] = None
    resolution: Optional[Tuple[int, int]] = None
    codecs: Optional[str] = None
    frame_rate: Optional[float] = None
    audio_group: Optional[str] = None


@dataclass
class HlsMedia:
    type: str
    group_id: str
    name: Optional[str] = None
    language: Optional[str] = None
    uri: Optional[str] = None
    default: bool = False
    autoselect: bool = False


@dataclass
class HlsPlaylist:
    base_url: str
    is_master: bool = False
    variants: List[HlsVariant] = field(default_factory=list)
    media: List[HlsMedia] = field(default_factory=list)
    segments: List[HlsSegment] = field(default_factory=list)
    target_duration: float = 0.0
    media_sequence: int = 0
    version: Optional[int] = None
    endlist: bool = False

    def best_variant(self) -> Optional[HlsVariant]:
        if not self.variants:
            return None
        return max(
            self.variants,
            key=lambda v: (
                (v.resolution[1] if v.resolution else 0),
                (v.frame_rate or 0),
                (v.bandwidth or 0),
            ),
        )


_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def parse_attributes(text: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for match in _ATTR_RE.finditer(text):
        key = match.group(1)
        value = match.group(2)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attrs[key] = value
    return attrs


def _parse_byterange(text: str) -> Optional[Tuple[int, int]]:
    text = text.strip()
    if not text:
        return None
    if "@" in text:
        length_s, offset_s = text.split("@", 1)
        return int(offset_s), int(length_s)
    return None, int(text)


def parse_m3u8(text: str, base_url: str) -> HlsPlaylist:
    playlist = HlsPlaylist(base_url=base_url)
    lines = [line.strip() for line in text.splitlines()]
    pending_duration: Optional[float] = None
    pending_range: Optional[Tuple[Optional[int], int]] = None
    pending_variant: Optional[Dict[str, str]] = None
    current_key: Optional[HlsKey] = None
    current_map: Optional[Tuple[str, Optional[Tuple[int, int]]]] = None
    last_range_end: Optional[int] = None
    seq = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending_variant = parse_attributes(line.split(":", 1)[1])
            playlist.is_master = True
            continue
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = parse_attributes(line.split(":", 1)[1])
            playlist.media.append(
                HlsMedia(
                    type=attrs.get("TYPE", ""),
                    group_id=attrs.get("GROUP-ID", ""),
                    name=attrs.get("NAME"),
                    language=attrs.get("LANGUAGE"),
                    uri=absolutize(base_url, attrs["URI"]) if attrs.get("URI") else None,
                    default=attrs.get("DEFAULT", "NO").upper() == "YES",
                    autoselect=attrs.get("AUTOSELECT", "NO").upper() == "YES",
                )
            )
            continue
        if line.startswith("#EXT-X-KEY:"):
            attrs = parse_attributes(line.split(":", 1)[1])
            method = attrs.get("METHOD", "NONE").upper()
            if method == "NONE":
                current_key = None
            else:
                uri = attrs.get("URI")
                current_key = HlsKey(
                    method=method,
                    uri=absolutize(base_url, uri) if uri else None,
                    iv=crypto.parse_iv(attrs.get("IV", "")),
                    keyformat=attrs.get("KEYFORMAT"),
                )
            continue
        if line.startswith("#EXT-X-MAP:"):
            attrs = parse_attributes(line.split(":", 1)[1])
            uri = attrs.get("URI")
            br = _parse_byterange(attrs.get("BYTERANGE", "")) if attrs.get("BYTERANGE") else None
            if uri:
                rng = None
                if br is not None:
                    offset, length = br
                    rng = (offset or 0, length)
                current_map = (absolutize(base_url, uri), rng)
            continue
        if line.startswith("#EXT-X-BYTERANGE:"):
            pending_range = _parse_byterange(line.split(":", 1)[1])
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            playlist.media_sequence = int(line.split(":", 1)[1].strip())
            seq = playlist.media_sequence
            continue
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                playlist.target_duration = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if line.startswith("#EXT-X-VERSION:"):
            try:
                playlist.version = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if line.startswith("#EXT-X-ENDLIST"):
            playlist.endlist = True
            continue
        if line.startswith("#EXTINF:"):
            payload = line.split(":", 1)[1]
            duration_s = payload.split(",", 1)[0].strip()
            try:
                pending_duration = float(duration_s)
            except ValueError:
                pending_duration = 0.0
            continue
        if line.startswith("#EXT-X-DISCONTINUITY"):
            # Mark the next segment.
            if playlist.segments:
                playlist.segments[-1].discontinuity = True
            continue
        if line.startswith("#"):
            continue

        # A URI line.
        uri = absolutize(base_url, line)
        if pending_variant is not None:
            resolution = None
            if pending_variant.get("RESOLUTION"):
                try:
                    w, h = pending_variant["RESOLUTION"].lower().split("x")
                    resolution = (int(w), int(h))
                except ValueError:
                    resolution = None
            playlist.variants.append(
                HlsVariant(
                    uri=uri,
                    bandwidth=_int_or_none(pending_variant.get("BANDWIDTH")),
                    average_bandwidth=_int_or_none(pending_variant.get("AVERAGE-BANDWIDTH")),
                    resolution=resolution,
                    codecs=pending_variant.get("CODECS"),
                    frame_rate=_float_or_none(pending_variant.get("FRAME-RATE")),
                    audio_group=pending_variant.get("AUDIO"),
                )
            )
            pending_variant = None
            continue

        # Media segment.
        byte_range = None
        if pending_range is not None:
            offset, length = pending_range
            if offset is None:
                offset = last_range_end or 0
            byte_range = (offset, length)
            last_range_end = offset + length
            pending_range = None
        segment = HlsSegment(
            uri=uri,
            duration=pending_duration or 0.0,
            sequence=seq,
            byte_range=byte_range,
            key=current_key,
            map_uri=current_map[0] if current_map else None,
            map_range=current_map[1] if current_map else None,
        )
        playlist.segments.append(segment)
        seq += 1
        pending_duration = None

    if not playlist.is_master and playlist.segments:
        playlist.is_master = False
    return playlist


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _float_or_none(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def fetch_playlist(client: HttpClient, url: str, headers: Optional[Dict[str, str]] = None) -> HlsPlaylist:
    text = client.get_text(url, headers=headers)
    return parse_m3u8(text, url)


def download_hls(
    client: HttpClient,
    url_or_playlist,
    dest: str,
    headers: Optional[Dict[str, str]] = None,
    jobs: int = 8,
    progress: Optional[SegmentProgress] = None,
    log: Optional[Log] = None,
    remux: bool = True,
) -> str:
    """Download an HLS stream to ``dest``.

    ``dest`` is the final media path; the container is inferred from the
    playlist (fMP4 if an ``EXT-X-MAP`` is present, otherwise MPEG-TS).
    Returns the path actually written.
    """
    log = log or Log("warn")
    headers = headers or {}

    if isinstance(url_or_playlist, HlsPlaylist):
        playlist = url_or_playlist
    else:
        playlist = fetch_playlist(client, url_or_playlist, headers=headers)

    if playlist.is_master:
        variant = playlist.best_variant()
        if not variant:
            raise ValueError("master playlist has no variants")
        log.info(f"selected variant {variant.resolution or ''} {variant.bandwidth or ''}".strip())
        playlist = fetch_playlist(client, variant.uri, headers=headers)

    if not playlist.segments:
        raise ValueError("playlist has no media segments")

    is_fmp4 = any(seg.map_uri for seg in playlist.segments)
    ext = ".mp4" if is_fmp4 else ".ts"
    work_dir = dest + ".sgseg"
    os.makedirs(work_dir, exist_ok=True)

    key_cache: Dict[str, bytes] = {}
    total = len(playlist.segments)
    done = 0
    written: List[str] = []

    init_path = None
    if is_fmp4:
        first_map = next(seg for seg in playlist.segments if seg.map_uri)
        init_path = os.path.join(work_dir, "init.mp4")
        _download_one(client, first_map.map_uri, init_path, headers, first_map.map_range, log)
        written.append(init_path)

    def work(index: int, segment: HlsSegment) -> str:
        seg_path = os.path.join(work_dir, f"{index:06d}{'.m4s' if is_fmp4 else '.ts'}")
        data = _download_bytes(client, segment.uri, headers, segment.byte_range, log)
        if segment.key and segment.key.method.upper() == "AES-128":
            data = _decrypt_segment(client, segment, data, key_cache, log)
        with open(seg_path, "wb") as fh:
            fh.write(data)
        return seg_path

    results: Dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(work, idx, seg): idx for idx, seg in enumerate(playlist.segments)}
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
            done += 1
            if progress:
                progress(done, total)

    for idx in range(total):
        written.append(results[idx])

    raw = dest + ext
    with open(raw, "wb") as out:
        for path in written:
            with open(path, "rb") as fh:
                shutil.copyfileobj(fh, out, 1 << 20)

    shutil.rmtree(work_dir, ignore_errors=True)

    if remux and ext == ".ts":
        final = _try_remux(raw, dest, log)
        if final:
            try:
                os.remove(raw)
            except OSError:
                pass
            return final
    return raw


def _download_bytes(
    client: HttpClient,
    url: str,
    headers: Dict[str, str],
    byte_range: Optional[Tuple[int, int]],
    log: Log,
) -> bytes:
    rng = None
    if byte_range is not None:
        offset, length = byte_range
        rng = f"bytes={offset}-{offset + length - 1}"
    return client.get(url, headers=headers, byte_range=rng).body


def _download_one(
    client: HttpClient,
    url: str,
    path: str,
    headers: Dict[str, str],
    byte_range: Optional[Tuple[int, int]],
    log: Log,
) -> str:
    with open(path, "wb") as fh:
        fh.write(_download_bytes(client, url, headers, byte_range, log))
    return path


def _decrypt_segment(
    client: HttpClient,
    segment: HlsSegment,
    data: bytes,
    key_cache: Dict[str, bytes],
    log: Log,
) -> bytes:
    key = segment.key
    assert key is not None
    if key.method.upper() != "AES-128":
        log.warn(f"unsupported HLS encryption method {key.method}; leaving segment as-is")
        return data
    if not key.uri:
        raise ValueError("AES-128 key without URI")
    if key.uri not in key_cache:
        key_cache[key.uri] = client.get_bytes(key.uri)
    key_bytes = key_cache[key.uri]
    iv = key.iv or crypto.sequence_iv(segment.sequence)
    decrypted = crypto.cbc_decrypt(key_bytes, iv, data)
    return crypto.pkcs7_unpad(decrypted)


def _try_remux(raw: str, dest: str, log: Log) -> Optional[str]:
    from . import muxer

    if not muxer.has_ffmpeg():
        return None
    target = dest if dest.endswith(".mp4") else dest + ".mp4"
    return muxer.remux(raw, target, log=log)


__all__ = [
    "HlsPlaylist",
    "HlsVariant",
    "HlsSegment",
    "HlsKey",
    "parse_m3u8",
    "parse_attributes",
    "fetch_playlist",
    "download_hls",
]
