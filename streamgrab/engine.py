"""The download engine: resolve a URL, pick a format, download it."""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Union

from . import dash, hls, muxer
from .downloader import SegmentedDownloader
from .extractor import Extractor, default_extractors, resolve as resolve_url
from .http import HttpClient, load_cookie_file
from .models import Format, MediaInfo
from .util import Log, ensure_dir, human_size, sanitize_filename


class Engine:
    def __init__(
        self,
        jobs: int = 8,
        out_dir: str = ".",
        log_level: str = "info",
        cookies: Optional[Dict[str, str]] = None,
        cookie_file: Optional[str] = None,
        proxy: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        retries: int = 3,
        extractors: Optional[List[Extractor]] = None,
    ) -> None:
        self.log = Log(log_level)
        self.jobs = max(1, jobs)
        self.out_dir = out_dir
        cookie_jar: Dict[str, str] = {}
        if cookie_file:
            cookie_jar.update(load_cookie_file(cookie_file))
        if cookies:
            cookie_jar.update(cookies)
        self.client = HttpClient(
            headers=headers,
            timeout=timeout,
            retries=retries,
            cookies=cookie_jar,
            proxy=proxy,
        )
        self.extractors = extractors or default_extractors()

    # -- resolution --------------------------------------------------------
    def resolve(self, url: str, headers: Optional[Dict[str, str]] = None) -> MediaInfo:
        self.log.debug(f"resolving {url}")
        info = resolve_url(url, self.client, extractors=self.extractors, headers=headers)
        self.log.info(f"extractor={info.extractor} title={info.title!r} formats={len(info.formats)}")
        return info

    # -- selection ---------------------------------------------------------
    def select(self, media: MediaInfo, selector: str = "best", audio_only: bool = False) -> Format:
        if not media.formats:
            raise ValueError("no formats available")
        selector = (selector or "best").strip()
        if audio_only or selector == "bestaudio":
            return media.best(prefer_audio=True)
        if selector == "best":
            return media.best(prefer_audio=False)
        if selector == "worst":
            return min(media.formats, key=lambda f: (f.height or 0, f.tbr or 0))
        for fmt in media.formats:
            if fmt.format_id == selector:
                return fmt
        if selector.isdigit():
            for fmt in media.formats:
                if fmt.height == int(selector):
                    return fmt
        raise ValueError(f"no format matching {selector!r}")

    # -- download ----------------------------------------------------------
    def download(
        self,
        target: Union[str, MediaInfo],
        selector: str = "best",
        out: Optional[str] = None,
        audio_only: bool = False,
        mp3: bool = False,
        progress: bool = True,
    ) -> List[str]:
        media = target if isinstance(target, MediaInfo) else self.resolve(target)
        fmt = self.select(media, selector, audio_only=audio_only)
        self.log.info(f"selected: {fmt.label()}")

        stem = self._stem(media, out)
        headers = dict(media.http_headers)
        headers.update(fmt.http_headers or {})
        progress_cb = _ProgressPrinter(enabled=progress, log=self.log)

        if fmt.protocol == "hls":
            dest = stem + ".mp4"
            path = hls.download_hls(
                self.client, fmt.url, dest, headers=headers,
                jobs=self.jobs, progress=progress_cb, log=self.log,
            )
            outputs = [path]
        elif fmt.protocol == "dash":
            dest = stem + ".mp4"
            manifest = media.extra.get("manifest")
            is_audio = fmt.is_audio_only
            outputs = dash.download_dash(
                self.client, manifest or fmt.url, dest, headers=headers,
                jobs=self.jobs, progress=progress_cb, log=self.log,
                video_id=None if is_audio else fmt.format_id,
                audio_id=fmt.format_id if is_audio else None,
            )
        else:
            dest = stem + "." + (fmt.ext or "mp4")
            result = SegmentedDownloader(
                self.client, jobs=self.jobs, progress=progress_cb, log=self.log
            ).download(
                fmt.url, dest, headers=headers,
                expected_size=fmt.filesize,
                content_type=fmt.acodec if fmt.is_audio_only else None,
            )
            outputs = [result.path]
            if fmt.audio_url and not audio_only:
                audio_dest = stem + ".audio.m4a"
                audio_result = SegmentedDownloader(
                    self.client, jobs=self.jobs, log=self.log
                ).download(fmt.audio_url, audio_dest, headers=headers)
                if muxer.has_ffmpeg():
                    merged = muxer.mux(result.path, audio_result.path, dest, log=self.log)
                    if merged:
                        for tmp in (result.path, audio_result.path):
                            try:
                                os.remove(tmp)
                            except OSError:
                                pass
                        outputs = [merged]
                else:
                    outputs.append(audio_result.path)

        if mp3:
            outputs = self._to_mp3(outputs)

        for path in outputs:
            if os.path.exists(path):
                self.log.info(f"saved {path} ({human_size(os.path.getsize(path))})")
        return outputs

    def _stem(self, media: MediaInfo, out: Optional[str]) -> str:
        if out:
            if os.path.isdir(out) or out.endswith(os.sep):
                return os.path.join(ensure_dir(out), sanitize_filename(media.title))
            parent = os.path.dirname(out)
            if parent:
                ensure_dir(parent)
            return out
        ensure_dir(self.out_dir)
        return os.path.join(self.out_dir, sanitize_filename(media.title))

    def _to_mp3(self, outputs: List[str]) -> List[str]:
        if not muxer.has_ffmpeg():
            self.log.warn("ffmpeg not found; cannot transcode to mp3")
            return outputs
        converted: List[str] = []
        for path in outputs:
            if path.lower().endswith(".mp3"):
                converted.append(path)
                continue
            target = os.path.splitext(path)[0] + ".mp3"
            result = muxer.transcode_audio(path, target, log=self.log)
            if result:
                converted.append(result)
            else:
                converted.append(path)
        return converted


class _ProgressPrinter:
    """Render a compact progress bar on stderr when attached to a TTY."""

    def __init__(self, enabled: bool, log: Log) -> None:
        self.enabled = enabled and sys.stderr.isatty()
        self.log = log
        self._last = -1

    def __call__(self, done: int, total: int) -> None:
        if not self.enabled:
            return
        total = total or 0
        percent = int(done * 100 / total) if total else 0
        if percent == self._last:
            return
        self._last = percent
        width = 28
        filled = int(width * percent / 100)
        bar = "#" * filled + "-" * (width - filled)
        sys.stderr.write(f"\r  [{bar}] {percent:3d}%  {human_size(done)}/{human_size(total)}")
        sys.stderr.flush()
        if total and done >= total:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._last = -1


__all__ = ["Engine", "MediaInfo", "Format"]
