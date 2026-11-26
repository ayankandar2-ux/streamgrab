"""Command-line interface."""

from __future__ import annotations

import argparse
from typing import Dict, List, Optional

from . import __version__
from .engine import Engine
from .util import human_duration, human_size


def _parse_headers(values: Optional[List[str]]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for item in values or []:
        if ":" in item:
            name, value = item.split(":", 1)
            headers[name.strip()] = value.strip()
    return headers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="streamgrab",
        description="Download video/audio from direct links, HLS and DASH manifests.",
    )
    parser.add_argument("urls", nargs="+", metavar="URL", help="page or manifest URL")
    parser.add_argument("-f", "--format", default="best",
                        help="format selector: best, worst, bestaudio, an id, or a height (e.g. 720)")
    parser.add_argument("-o", "--out", default=None,
                        help="output file or directory")
    parser.add_argument("-j", "--jobs", type=int, default=8,
                        help="parallel connections / segment workers (default 8)")
    parser.add_argument("--list", action="store_true", help="list formats and exit")
    parser.add_argument("--audio", action="store_true", help="download best audio only")
    parser.add_argument("--mp3", action="store_true", help="transcode the result to mp3")
    parser.add_argument("--cookies", default=None, help="Netscape cookies.txt or 'k=v; k2=v2'")
    parser.add_argument("--proxy", default=None, help="HTTP/HTTPS proxy URL")
    parser.add_argument("--header", action="append", metavar="NAME:VALUE",
                        help="extra request header (repeatable)")
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout seconds")
    parser.add_argument("--retries", type=int, default=3, help="retry count")
    parser.add_argument("-q", "--quiet", action="store_true", help="only errors")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"streamgrab {__version__}")
    return parser


def _print_formats(engine: Engine, url: str) -> None:
    media = engine.resolve(url)
    print(f"title: {media.title}")
    if media.duration:
        print(f"duration: {human_duration(media.duration)}")
    if media.extractor:
        print(f"extractor: {media.extractor}")
    print(f"formats: {len(media.formats)}")
    for fmt in media.formats:
        size = human_size(fmt.filesize) if fmt.filesize else ""
        print(f"  {fmt.format_id:<12} {fmt.protocol:<5} {fmt.ext:<4} {fmt.label()} {size}".rstrip())


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = "debug" if args.verbose else ("error" if args.quiet else "info")
    engine = Engine(
        jobs=args.jobs,
        out_dir=args.out or ".",
        log_level=level,
        cookie_file=args.cookies,
        proxy=args.proxy,
        headers=_parse_headers(args.header),
        timeout=args.timeout,
        retries=args.retries,
    )

    exit_code = 0
    for url in args.urls:
        try:
            if args.list:
                _print_formats(engine, url)
                continue
            engine.download(
                url,
                selector=args.format,
                out=args.out,
                audio_only=args.audio,
                mp3=args.mp3,
            )
        except Exception as exc:
            engine.log.error(f"{url}: {exc}")
            if args.verbose:
                import traceback

                traceback.print_exc()
            exit_code = 1
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
