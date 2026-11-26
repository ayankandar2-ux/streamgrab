"""End-to-end HLS download test against a local server (plain and AES-128)."""

import http.server
import os
import threading

import pytest

from streamgrab import crypto, hls
from streamgrab.http import HttpClient

SEG0 = b"\x47" + b"segment-zero-payload" * 40
SEG1 = b"\x47" + b"segment-one-payload!" * 40
KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
IV = bytes.fromhex("0f0e0d0c0b0a09080706050403020100")


def _make_handler(encrypted: bool):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/media.m3u8":
                if encrypted:
                    key_line = '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x' + IV.hex() + "\n"
                else:
                    key_line = ""
                body = (
                    "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n"
                    + key_line
                    + "#EXTINF:4.0,\nseg0.ts\n#EXTINF:4.0,\nseg1.ts\n#EXT-X-ENDLIST\n"
                ).encode()
                self._send(200, body, "application/vnd.apple.mpegurl")
            elif path == "/key.bin":
                self._send(200, KEY, "application/octet-stream")
            elif path == "/seg0.ts":
                self._send(200, crypto.cbc_encrypt(KEY, IV, SEG0) if encrypted else SEG0, "video/mp2t")
            elif path == "/seg1.ts":
                self._send(200, crypto.cbc_encrypt(KEY, IV, SEG1) if encrypted else SEG1, "video/mp2t")
            else:
                self._send(404, b"no", "text/plain")

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@pytest.fixture(params=[False, True], ids=["plain", "aes128"])
def server(request):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(request.param))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/media.m3u8"
    httpd.shutdown()
    httpd.server_close()


def test_hls_download(server, tmp_path):
    dest = str(tmp_path / "out.mp4")
    path = hls.download_hls(
        HttpClient(), server, dest, jobs=2, remux=False
    )
    assert path.endswith(".ts")
    with open(path, "rb") as fh:
        data = fh.read()
    assert data == SEG0 + SEG1


def test_hls_download_parallel_segments(tmp_path):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(False))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/media.m3u8"
        dest = str(tmp_path / "out.mp4")
        path = hls.download_hls(HttpClient(), url, dest, jobs=4, remux=False)
        assert os.path.getsize(path) == len(SEG0) + len(SEG1)
    finally:
        httpd.shutdown()
        httpd.server_close()
