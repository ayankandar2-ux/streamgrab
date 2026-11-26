"""Tests for the segmented downloader against a local range-capable server."""

import http.server
import json
import os
import threading

import pytest

from streamgrab.downloader import SegmentedDownloader
from streamgrab.http import HttpClient

PAYLOAD = bytes((i * 37) % 256 for i in range(200_000))


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _range(self):
        header = self.headers.get("Range")
        if not header or not header.startswith("bytes="):
            return None
        spec = header[6:]
        start_s, end_s = spec.split("-", 1)
        start = int(start_s)
        end = int(end_s) if end_s else len(PAYLOAD) - 1
        return start, min(end, len(PAYLOAD) - 1)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        rng = self._range()
        if rng is None:
            body = PAYLOAD
            self.send_response(200)
        else:
            start, end = rng
            body = PAYLOAD[start:end + 1]
            self.send_response(206)
            self.send_header(
                "Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}"
            )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/file.bin"
    httpd.shutdown()
    httpd.server_close()


def test_segmented_download(server, tmp_path):
    dest = str(tmp_path / "out.bin")
    dl = SegmentedDownloader(HttpClient(), jobs=4, min_split_size=0)
    result = dl.download(server, dest)
    assert result.size == len(PAYLOAD)
    assert result.parts >= 2
    with open(dest, "rb") as fh:
        assert fh.read() == PAYLOAD


def test_single_stream_when_not_split(server, tmp_path):
    dest = str(tmp_path / "out.bin")
    dl = SegmentedDownloader(HttpClient(), jobs=4, min_split_size=10_000_000)
    result = dl.download(server, dest)
    assert result.parts == 1
    with open(dest, "rb") as fh:
        assert fh.read() == PAYLOAD


def test_cache_hit(server, tmp_path):
    dest = str(tmp_path / "out.bin")
    with open(dest, "wb") as fh:
        fh.write(PAYLOAD)
    dl = SegmentedDownloader(HttpClient(), jobs=4)
    result = dl.download(server, dest, expected_size=len(PAYLOAD))
    assert result.from_cache


def test_resume_from_state(server, tmp_path):
    dest = str(tmp_path / "out.bin")
    parts_dir = dest + ".sgparts"
    os.makedirs(parts_dir)
    half = len(PAYLOAD) // 2
    # Pretend part 0 finished, part 1 not started.
    with open(os.path.join(parts_dir, "00000.part"), "wb") as fh:
        fh.write(PAYLOAD[:half])
    state = {
        "url": server,
        "total": len(PAYLOAD),
        "chunk_size": half,
        "parts": [
            {"i": 0, "s": 0, "e": half - 1, "d": half},
            {"i": 1, "s": half, "e": len(PAYLOAD) - 1, "d": 0},
        ],
    }
    with open(dest + ".sgstate.json", "w", encoding="utf-8") as fh:
        json.dump(state, fh)

    dl = SegmentedDownloader(HttpClient(), jobs=2, min_split_size=0)
    result = dl.download(server, dest)
    assert result.resumed
    with open(dest, "rb") as fh:
        assert fh.read() == PAYLOAD
