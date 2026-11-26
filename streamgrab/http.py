"""Minimal HTTP client built on the standard library.

Why not ``requests``? The goal is a tool that installs with zero runtime
dependencies. Everything we need (headers, ranges, redirects, cookies,
retries) is available from :mod:`urllib`.
"""

from __future__ import annotations

import gzip
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, Optional

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 streamgrab/0.1"
)


@dataclass
class HttpResponse:
    status: int
    headers: Dict[str, str]
    body: bytes
    url: str

    def header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.headers.get(name.lower(), default)

    @property
    def content_length(self) -> Optional[int]:
        value = self.header("content-length")
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None


def _lower_headers(raw: Iterable[tuple]) -> Dict[str, str]:
    return {k.lower(): v for k, v in raw}


def load_cookie_file(path: str) -> Dict[str, str]:
    """Parse a Netscape ``cookies.txt`` or a ``name=value; name2=value2`` string."""
    cookies: Dict[str, str] = {}
    if not path:
        return cookies
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return cookies
    if "# Netscape HTTP Cookie File" in text or "\t" in text:
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    else:
        for part in text.split(";"):
            if "=" in part:
                name, value = part.split("=", 1)
                cookies[name.strip()] = value.strip()
    return cookies


class HttpClient:
    def __init__(
        self,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 0.8,
        cookies: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
    ) -> None:
        self.headers = {"User-Agent": DEFAULT_UA, "Accept-Encoding": "identity"}
        if headers:
            self.headers.update(headers)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.cookies = dict(cookies or {})
        self.proxy = proxy
        self._opener = self._build_opener()

    def _build_opener(self) -> urllib.request.OpenerDirector:
        handlers = []
        if self.proxy:
            handlers.append(
                urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy})
            )
        return urllib.request.build_opener(*handlers)

    # -- header assembly ---------------------------------------------------
    def _compose_headers(
        self,
        extra: Optional[Dict[str, str]] = None,
        byte_range: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = dict(self.headers)
        if self.cookies:
            cookie = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            headers["Cookie"] = cookie
        if extra:
            headers.update({k: v for k, v in extra.items() if v is not None})
        if byte_range:
            headers["Range"] = byte_range
        return headers

    # -- single request ----------------------------------------------------
    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        byte_range: Optional[str] = None,
        allow_status: Iterable[int] = (200, 206),
    ) -> HttpResponse:
        last_err: Optional[BaseException] = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                url,
                data=data,
                method=method,
                headers=self._compose_headers(headers, byte_range),
            )
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    body = _maybe_decompress(raw, dict(resp.headers.items()))
                    return HttpResponse(
                        status=resp.status,
                        headers=_lower_headers(resp.headers.items()),
                        body=body,
                        url=resp.geturl(),
                    )
            except urllib.error.HTTPError as exc:
                if exc.code in allow_status:
                    raw = exc.read()
                    return HttpResponse(
                        status=exc.code,
                        headers=_lower_headers(exc.headers.items()),
                        body=_maybe_decompress(raw, dict(exc.headers.items())),
                        url=url,
                    )
                last_err = exc
                if exc.code in (400, 401, 403, 404, 410):
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_err = exc
            if attempt < self.retries:
                time.sleep(self.backoff * (2 ** attempt))
        assert last_err is not None
        raise last_err

    def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        byte_range: Optional[str] = None,
    ) -> HttpResponse:
        return self.request(url, "GET", headers=headers, byte_range=byte_range)

    def get_bytes(
        self, url: str, headers: Optional[Dict[str, str]] = None
    ) -> bytes:
        return self.get(url, headers=headers).body

    def get_text(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
    ) -> str:
        body = self.get_bytes(url, headers=headers)
        return _decode_text(body, encoding)

    def head(
        self, url: str, headers: Optional[Dict[str, str]] = None
    ) -> HttpResponse:
        return self.request(url, "HEAD", headers=headers, allow_status=(200, 204, 206))

    def stream(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        byte_range: Optional[str] = None,
        chunk_size: int = 1 << 16,
    ) -> Iterator[bytes]:
        """Yield the body in chunks. Retries only before the first chunk."""
        req = urllib.request.Request(
            url,
            method="GET",
            headers=self._compose_headers(headers, byte_range),
        )
        last_err: Optional[BaseException] = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._opener.open(req, timeout=self.timeout)
                try:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
                    return
                finally:
                    resp.close()
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_err = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** attempt))
        assert last_err is not None
        raise last_err


def _decode_text(body: bytes, encoding: Optional[str]) -> str:
    if encoding:
        return body.decode(encoding, errors="replace")
    for enc in ("utf-8", "latin-1"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def _maybe_decompress(raw: bytes, headers: Dict[str, str]) -> bytes:
    enc = headers.get("Content-Encoding", headers.get("content-encoding", "")).lower()
    try:
        if "gzip" in enc:
            return gzip.decompress(raw)
        if "deflate" in enc:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except (OSError, zlib.error):
        return raw
    return raw


def absolutize(base: str, ref: str) -> str:
    """Resolve ``ref`` against ``base`` (which may itself be a URL or path)."""
    if not ref:
        return base
    return urllib.parse.urljoin(base, ref)


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc
    except ValueError:
        return ""


def origin_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return f"{parts.scheme}://{parts.netloc}"


def looks_like_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value or "", re.I))


def guess_ext_from_url(url: str, default: str = "mp4") -> str:
    path = urllib.parse.urlsplit(url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower().lstrip(".")
    if ext and len(ext) <= 5 and ext.isalnum():
        return "m4a" if ext == "m4a" else ext
    return default


__all__ = [
    "HttpClient",
    "HttpResponse",
    "DEFAULT_UA",
    "load_cookie_file",
    "absolutize",
    "host_of",
    "origin_of",
    "looks_like_url",
    "guess_ext_from_url",
]
