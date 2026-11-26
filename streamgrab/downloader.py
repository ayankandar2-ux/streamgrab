"""Segmented, resumable HTTP downloader.

This is the transfer core: it splits a file into byte ranges, downloads the
ranges concurrently, tracks progress in a sidecar state file, and resumes
interrupted transfers. Servers that ignore ``Range`` fall back to a single
stream automatically.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .http import HttpClient
from .util import Log

ProgressFn = Callable[[int, int], None]


@dataclass
class DownloadResult:
    path: str
    size: int
    resumed: bool = False
    parts: int = 1
    from_cache: bool = False


@dataclass
class _Part:
    index: int
    start: int
    end: int  # inclusive
    done: int = 0

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass
class _State:
    url: str
    total: int
    parts: List[_Part]
    chunk_size: int = 1 << 20

    def to_json(self) -> str:
        return json.dumps(
            {
                "url": self.url,
                "total": self.total,
                "chunk_size": self.chunk_size,
                "parts": [
                    {"i": p.index, "s": p.start, "e": p.end, "d": p.done}
                    for p in self.parts
                ],
            }
        )

    @classmethod
    def from_json(cls, text: str) -> "_State":
        data = json.loads(text)
        parts = [
            _Part(index=p["i"], start=p["s"], end=p["e"], done=p["d"])
            for p in data["parts"]
        ]
        return cls(
            url=data["url"],
            total=data["total"],
            parts=parts,
            chunk_size=data.get("chunk_size", 1 << 20),
        )


class SegmentedDownloader:
    def __init__(
        self,
        client: HttpClient,
        jobs: int = 8,
        min_split_size: int = 4 << 20,
        retries: int = 3,
        progress: Optional[ProgressFn] = None,
        log: Optional[Log] = None,
    ) -> None:
        self.client = client
        self.jobs = max(1, jobs)
        self.min_split_size = min_split_size
        self.retries = max(0, retries)
        self.progress = progress
        self.log = log or Log("warn")

    # -- public API --------------------------------------------------------
    def download(
        self,
        url: str,
        dest: str,
        headers: Optional[Dict[str, str]] = None,
        expected_size: Optional[int] = None,
        content_type: Optional[str] = None,
        max_jobs: Optional[int] = None,
    ) -> DownloadResult:
        headers = headers or {}
        if expected_size and os.path.exists(dest) and os.path.getsize(dest) == expected_size:
            self.log.info(f"already complete: {dest}")
            return DownloadResult(dest, expected_size, from_cache=True)

        info = self._probe(url, headers)
        total = info["total"] or expected_size or 0
        ranges_ok = info["ranges"] and total > 0

        if os.path.exists(dest) and total and os.path.getsize(dest) == total:
            return DownloadResult(dest, total, from_cache=True)

        jobs = self.jobs if max_jobs is None else max(1, max_jobs)

        if not ranges_ok or total < self.min_split_size or jobs == 1:
            self.log.debug(f"single-stream download ({total} bytes, ranges={ranges_ok})")
            size = self._single(url, dest, headers, total, content_type)
            return DownloadResult(dest, size, parts=1)

        return self._multi(url, dest, headers, total, jobs)

    # -- probing -----------------------------------------------------------
    def _probe(self, url: str, headers: Dict[str, str]) -> Dict[str, object]:
        try:
            resp = self.client.head(url, headers=headers)
            total = resp.content_length
            accept = (resp.header("accept-ranges") or "").lower()
            if total is None and resp.header("content-range"):
                total = _total_from_content_range(resp.header("content-range"))
            return {"total": total, "ranges": accept == "bytes" or total is not None}
        except Exception:
            pass
        # HEAD blocked: probe with a one-byte range request.
        try:
            resp = self.client.get(url, headers=headers, byte_range="bytes=0-0")
            cr = resp.header("content-range")
            total = _total_from_content_range(cr) if cr else None
            return {"total": total, "ranges": resp.status == 206}
        except Exception as exc:
            self.log.debug(f"probe failed ({exc}); assuming single stream")
            return {"total": None, "ranges": False}

    # -- single stream -----------------------------------------------------
    def _single(
        self,
        url: str,
        dest: str,
        headers: Dict[str, str],
        total: int,
        content_type: Optional[str],
    ) -> int:
        tmp = dest + ".sgpart"
        done = 0
        req_headers = dict(headers)
        if content_type:
            req_headers.setdefault("Accept", content_type)
        with open(tmp, "wb") as fh:
            for chunk in self.client.stream(url, headers=req_headers):
                fh.write(chunk)
                done += len(chunk)
                if self.progress:
                    self.progress(done, total or done)
        os.replace(tmp, dest)
        return done

    # -- multi stream ------------------------------------------------------
    def _multi(
        self,
        url: str,
        dest: str,
        headers: Dict[str, str],
        total: int,
        jobs: int,
    ) -> DownloadResult:
        state_path = dest + ".sgstate.json"
        parts_dir = dest + ".sgparts"
        os.makedirs(parts_dir, exist_ok=True)

        state = self._load_state(state_path, url, total)
        resumed = False
        if state is None:
            chunk = max(1, -(-total // jobs))
            parts: List[_Part] = []
            start = 0
            index = 0
            while start < total:
                end = min(start + chunk - 1, total - 1)
                parts.append(_Part(index, start, end))
                start = end + 1
                index += 1
            state = _State(url=url, total=total, parts=parts)
            self._save_state(state_path, state)
        else:
            resumed = True
            self.log.info(f"resuming {dest} ({sum(p.done for p in state.parts)}/{total})")

        counter = _Counter(sum(p.done for p in state.parts), total, self.progress)
        lock = threading.Lock()

        def fetch(part: _Part) -> None:
            part_file = os.path.join(parts_dir, f"{part.index:05d}.part")
            have = os.path.getsize(part_file) if os.path.exists(part_file) else 0
            have = min(have, part.length)
            if have == part.length:
                with lock:
                    part.done = part.length
                return
            begin = part.start + have
            rng = f"bytes={begin}-{part.end}"
            mode = "ab" if have else "wb"
            attempt = 0
            while True:
                try:
                    with open(part_file, mode) as fh:
                        for chunk in self.client.stream(url, headers=headers, byte_range=rng):
                            fh.write(chunk)
                            with lock:
                                part.done += len(chunk)
                            counter.add(len(chunk))
                    break
                except Exception as exc:
                    attempt += 1
                    if attempt > self.retries:
                        raise
                    self.log.warn(f"part {part.index} retry {attempt}: {exc}")
                    time.sleep(0.8 * (2 ** (attempt - 1)))
                    have = os.path.getsize(part_file) if os.path.exists(part_file) else 0
                    have = min(have, part.length)
                    begin = part.start + have
                    rng = f"bytes={begin}-{part.end}"
                    mode = "ab" if have else "wb"
                    with lock:
                        part.done = have

        with ThreadPoolExecutor(max_workers=min(jobs, len(state.parts))) as pool:
            futures = {pool.submit(fetch, p): p for p in state.parts}
            for fut in as_completed(futures):
                fut.result()

        # Merge in order.
        tmp = dest + ".sgmerge"
        with open(tmp, "wb") as out:
            for part in sorted(state.parts, key=lambda p: p.start):
                part_file = os.path.join(parts_dir, f"{part.index:05d}.part")
                with open(part_file, "rb") as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
        size = os.path.getsize(tmp)
        if total and size != total:
            raise IOError(f"size mismatch after merge: got {size}, expected {total}")
        os.replace(tmp, dest)

        # Cleanup.
        for part in state.parts:
            try:
                os.remove(os.path.join(parts_dir, f"{part.index:05d}.part"))
            except OSError:
                pass
        try:
            os.rmdir(parts_dir)
        except OSError:
            pass
        try:
            os.remove(state_path)
        except OSError:
            pass
        return DownloadResult(dest, size, resumed=resumed, parts=len(state.parts))

    # -- state -------------------------------------------------------------
    def _load_state(self, path: str, url: str, total: int) -> Optional[_State]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = _State.from_json(fh.read())
        except (OSError, ValueError, KeyError):
            return None
        if state.url != url or state.total != total:
            return None
        return state

    def _save_state(self, path: str, state: _State) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(state.to_json())
        os.replace(tmp, path)


class _Counter:
    def __init__(self, done: int, total: int, callback: Optional[ProgressFn]) -> None:
        self.done = done
        self.total = total
        self.callback = callback
        self.lock = threading.Lock()

    def add(self, n: int) -> None:
        if not self.callback:
            return
        with self.lock:
            self.done += n
            self.callback(self.done, self.total)


def _total_from_content_range(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    # bytes 0-0/12345
    try:
        return int(value.rsplit("/", 1)[1])
    except (ValueError, IndexError):
        return None


__all__ = ["SegmentedDownloader", "DownloadResult"]
