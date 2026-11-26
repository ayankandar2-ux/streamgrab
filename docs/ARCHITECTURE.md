# Architecture

This document explains how `streamgrab` is put together and why.

## Goals

1. **Readable.** A small engine you can audit end-to-end.
2. **Dependency-light.** Standard library by default.
3. **Composable.** Extractors, transfer and muxing are independent layers.
4. **Robust.** Resumable downloads, graceful degradation without FFmpeg.

## Layered design

```
┌────────────┐   URL    ┌────────────┐  MediaInfo   ┌──────────┐
│    CLI     │ ───────▶ │ Extractor  │ ───────────▶ │ Selector │
└────────────┘          └────────────┘              └────┬─────┘
                                                        │ Format
                        ┌───────────────────────────────▼──────────┐
                        │              Transfer                     │
                        │  http ──▶ SegmentedDownloader             │
                        │  hls  ──▶ segments → decrypt → concat     │
                        │  dash ──▶ reps → segments → concat        │
                        └───────────────────┬──────────────────────┘
                                            │ files
                        ┌───────────────────▼──────────┐
                        │            Muxer             │
                        │  ffmpeg -c copy / transcode  │
                        └──────────────────────────────┘
```

### Extractor layer

`Extractor.matches(url)` decides ownership; `Extractor.extract(url, client)`
returns a `MediaInfo`. Extractors are stateless and must not download media.
The registry (`extractor/registry.py`) sorts by `priority` and tries each in
order, catching errors so a failed site-specific extractor falls through to the
generic HTML extractor.

`MediaInfo.formats` is a flat list of `Format`. A `Format` records its
`protocol` (`http`, `hls`, `dash`), codecs, dimensions, bitrate and optional
`audio_url` for split streams.

### Transfer layer

#### Segmented HTTP

Algorithm:

1. Probe size and range support.
2. If unsupported, small, or `jobs == 1`: stream to `dest.sgpart`, then rename.
3. Otherwise:
   - Split `[0, total)` into `ceil(total / jobs)`-sized parts.
   - Write each part to `dest.sgparts/NNNNN.part` with its own `Range` header.
   - Persist part offsets and byte counts to `dest.sgstate.json`.
   - On resume, read the state, skip completed parts and continue partial ones.
   - Merge parts in order, verify total size, atomically replace `dest`.

State machine per part: `pending → in_progress → done`. The state file is
rewritten after each part completes; per-byte progress is tracked in memory
(and surfaced through the progress callback) to avoid excessive disk writes.

Concurrency uses `ThreadPoolExecutor`; each worker owns a distinct part file, so
there are no shared-writer races.

#### HLS

`parse_m3u8` produces either a master playlist (variants) or a media playlist
(segments). `download_hls`:

1. Selects the best variant if the input is a master playlist.
2. Fetches the media playlist.
3. Fetches `EXT-X-MAP` initialization data if present (fMP4).
4. Downloads segments concurrently to `dest.sgseg/`.
5. For `AES-128` segments: fetch the key (cached per URI), derive the IV (explicit
   or the big-endian media sequence number), CBC-decrypt, strip PKCS#7 padding.
6. Concatenate in sequence order.
7. If MPEG-TS and FFmpeg is available, remux to MP4.

`EXT-X-BYTERANGE` is honored by requesting the exact byte span. Discontinuities
are recorded per segment for future codec-boundary handling.

#### DASH

`parse_mpd` walks `Period → AdaptationSet → Representation` and resolves
addressing into an explicit segment list:

- **SegmentTemplate**: substitutes `$RepresentationID$`, `$Number$`, `$Time$`,
  `$Bandwidth$`, `$Width$`, `$Height$`; expands `SegmentTimeline` `S` elements
  (with `r` repeats) or computes a fixed count from `duration`/`timescale`.
- **SegmentList**: reads `Initialization` and `SegmentURL` entries with optional
  byte ranges.
- **SegmentBase**: treats the representation as a single file.

Representations are partitioned into video and audio; the best of each is
downloaded and muxed.

### Muxer layer

FFmpeg is invoked through argument lists (never a shell) to avoid quoting issues.
`mux` uses `-c copy` and explicit stream maps, so video/audio are combined without
quality loss. Absence of FFmpeg is a non-fatal condition: the caller receives the
separate files.

## Failure and degradation

| Condition | Behavior |
|---|---|
| `HEAD` blocked | probe with `bytes=0-0` |
| No `Range` support | single-stream download |
| Interrupted transfer | resume from `.sgstate.json` |
| Unknown segment size | no preallocation; append as bytes arrive |
| No `cryptography` | pure-Python AES |
| No FFmpeg | keep raw/separate files, warn |
| Extractor error | try next extractor in the registry |

## Security notes

- No shell execution; FFmpeg is called with an argument vector.
- Cookies and headers are only sent to the target host supplied by the caller.
- The tool performs no DRM circumvention and no credential attacks.
- Download only content you are authorized to access.

## Extension points

- **New site**: subclass `Extractor`, set `priority`, register it.
- **New protocol**: add a module exposing `download_*` and a `Format.protocol`
  value, then branch in `Engine.download`.
- **Different storage**: wrap `SegmentedDownloader` or replace its merge step.
