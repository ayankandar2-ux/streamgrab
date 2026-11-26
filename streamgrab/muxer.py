"""FFmpeg / FFprobe integration.

FFmpeg is optional. When present it is used to mux separate video and audio
streams into a single container and to transcode audio. When absent the
caller keeps the raw files.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from .util import Log


def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def ffprobe_path() -> Optional[str]:
    return shutil.which("ffprobe")


def has_ffmpeg() -> bool:
    return ffmpeg_path() is not None


def _run(cmd: List[str], log: Optional[Log] = None, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    if log:
        log.debug("exec: " + " ".join(cmd))
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def probe(path: str, log: Optional[Log] = None) -> Dict[str, object]:
    exe = ffprobe_path()
    if not exe:
        return {}
    result = _run(
        [
            exe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ],
        log=log,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        return {}


def mux(
    video: str,
    audio: Optional[str],
    out: str,
    log: Optional[Log] = None,
    copy: bool = True,
    extra_args: Optional[List[str]] = None,
) -> Optional[str]:
    """Mux ``video`` (and optional ``audio``) into ``out``.

    Returns the output path on success, ``None`` if ffmpeg is unavailable or
    the operation failed.
    """
    exe = ffmpeg_path()
    if not exe:
        return None
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", video]
    if audio:
        cmd += ["-i", audio]
    if copy:
        cmd += ["-c", "copy"]
    if audio and copy:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    elif audio:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    if extra_args:
        cmd += extra_args
    cmd += ["-movflags", "+faststart", out]
    result = _run(cmd, log=log)
    if result.returncode != 0:
        if log:
            log.warn("ffmpeg mux failed: " + result.stderr.decode("utf-8", "replace")[-400:])
        return None
    return out


def remux(src: str, out: str, log: Optional[Log] = None) -> Optional[str]:
    return mux(src, None, out, log=log, copy=True)


def concat(parts: List[str], out: str, log: Optional[Log] = None) -> Optional[str]:
    """Concatenate media files losslessly using the ffmpeg concat demuxer."""
    exe = ffmpeg_path()
    if not exe or not parts:
        return None
    list_path = out + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as fh:
        for part in parts:
            escaped = part.replace("'", "'\\''")
            fh.write(f"file '{escaped}'\n")
    try:
        result = _run(
            [exe, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
             "-safe", "0", "-i", list_path, "-c", "copy", out],
            log=log,
        )
        return out if result.returncode == 0 else None
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def transcode_audio(
    src: str,
    out: str,
    bitrate: str = "192k",
    codec: str = "libmp3lame",
    log: Optional[Log] = None,
) -> Optional[str]:
    exe = ffmpeg_path()
    if not exe:
        return None
    result = _run(
        [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
         "-vn", "-c:a", codec, "-b:a", bitrate, out],
        log=log,
    )
    return out if result.returncode == 0 else None


__all__ = [
    "ffmpeg_path",
    "ffprobe_path",
    "has_ffmpeg",
    "probe",
    "mux",
    "remux",
    "concat",
    "transcode_audio",
]
