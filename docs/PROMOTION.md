# Launch & promotion kit

Ready-to-use copy for announcing **streamgrab**. Use what fits each venue, and
follow that community's self-promotion rules — unsolicited cross-posting reads
as spam and gets removed.

- Repo: https://github.com/ayankandar2-ux/streamgrab
- License: MIT
- One-liner: **A modular, dependency-light media download engine — segmented HTTP, HLS and DASH with optional FFmpeg muxing.**

## Positioning

- **What it is:** a small, readable Python engine that downloads from direct
  links, `.m3u8` and `.mpd`, with resumable parallel transfer and optional FFmpeg muxing.
- **Who it's for:** developers who want a hackable reference implementation, not
  a giant all-in-one app.
- **Differentiator:** zero runtime dependencies, pure-Python AES fallback,
  clean layer boundaries (extractor / transfer / muxer), fully tested on three OSes,
  and runs natively on Android through Termux with no root or proot.

## GitHub repo description (already set)

> Modular, dependency-light media download engine: segmented HTTP, HLS, DASH, FFmpeg muxing (Python).

Topics: `downloader` `hls` `dash` `m3u8` `mpd` `ffmpeg` `python` `video`

## Show HN

**Title:** Show HN: streamgrab – a small, dependency-free HLS/DASH downloader in Python

**Text:**

> I wanted a downloader I could read end-to-end and extend, so I built one. It
> resolves a URL to formats, fetches bytes with segmented parallel HTTP (with
> resume), handles HLS (including AES-128) and DASH, and muxes video+audio with
> FFmpeg when available.
>
> No runtime dependencies; pure-Python AES fallback; FFmpeg is optional.
> The design is split into extractor / transfer / muxer layers so each is easy
> to test and replace. 24 tests, CI on Linux/macOS/Windows, Python 3.9–3.13.
>
> Repo: https://github.com/ayankandar2-ux/streamgrab
> Happy to answer questions about the segmented-download state machine or the
> HLS/DASH parsing.

## Reddit

Post only where it's on-topic and the rules allow project sharing.

**r/termux** — title: *streamgrab: an HLS/DASH downloader that runs natively in Termux (no root, no proot)*

> I wrote a small download engine in pure Python — segmented HTTP with resume,
> HLS (m3u8 + AES-128) and DASH (MPD) — and it runs unmodified in Termux on
> arm64. No proot, no desktop, no root.
>
> Notes from testing on-device: install `python-cryptography` from `pkg` rather
> than pip (avoids a Rust build), `termux-setup-storage` then `-o
> ~/storage/downloads/` to land files in the normal Downloads folder, and
> `termux-wake-lock` for long jobs. `-j 4` is a better default on a phone than
> 16 — thermal throttling is real.
>
> There's a `scripts/termux-install.sh` that does the whole setup.
> MIT, zero runtime deps: https://github.com/ayankandar2-ux/streamgrab

**r/Python** — title: *streamgrab: a small HLS/DASH download engine with zero runtime deps*

> I built a compact downloader as a readable reference implementation:
> segmented parallel HTTP with resume, HLS (m3u8 + AES-128), DASH (MPD), and
> optional FFmpeg muxing. Extractor / transfer / muxer are separate layers, so
> you can plug in a site extractor without touching the engine.
>
> It's MIT, stdlib-only, and tested on Linux/macOS/Windows for Python 3.9–3.13.
> Code + design notes: https://github.com/ayankandar2-ux/streamgrab
> Feedback on the API and the resume logic welcome.

**r/selfhosted / r/DataHoarder** — angle: *resumable segmented downloads for your own media*

> Sharing a small tool I wrote for pulling HLS/DASH streams with resumable,
> multi-connection transfers. It keeps a state file per download so an
> interrupted job continues where it stopped, and it muxes split video/audio
> with FFmpeg. Useful if you archive streams you have rights to. MIT, no deps:
> https://github.com/ayankandar2-ux/streamgrab

## X / Twitter thread

1. Shipped **streamgrab** — a tiny, dependency-free media download engine in Python.
   Segmented HTTP, HLS, DASH, optional FFmpeg muxing. MIT.
   https://github.com/ayankandar2-ux/streamgrab
2. Design: URL → Extractor → MediaInfo → Selector → Transfer → Muxer.
   Each layer is testable on its own; add a site by subclassing `Extractor`.
3. Transfer does parallel byte ranges with a resume state file, and falls back to
   a single stream when the server ignores `Range`.
4. HLS handles `EXT-X-KEY` AES-128 (pure-Python fallback) and `EXT-X-MAP`;
   DASH handles `SegmentTemplate`/`SegmentTimeline`.
5. 24 tests, CI on Linux/macOS/Windows, Python 3.9–3.13. PRs and extractor
   plugins welcome.

## Dev.to / blog outline

1. Why another downloader: readability and layer boundaries.
2. The four layers, with the architecture diagram.
3. Deep dive: the segmented-download state machine (parts, resume, merge).
4. HLS: keys, IVs, init maps, byte ranges.
5. DASH: addressing modes and representation selection.
6. Testing strategy: local HTTP fixtures instead of live sites.
7. Extension points and roadmap.

## Checklist

- [x] Public repo with README, docs, LICENSE, CI
- [x] Topics + repo description
- [x] Hero banner, architecture and demo images in `docs/assets/`
- [x] GitHub Release `v0.1.0`
- [ ] Upload the banner as the repo **social preview** (Settings → General → Social preview)
- [ ] Optional: publish to PyPI (`pip install streamgrab`)
- [ ] Optional: submit to Awesome-Python-style lists (follow their contribution rules)

## Etiquette

- Disclose that you're the author.
- Read each community's self-promotion rules; many restrict frequency.
- Don't mass-DM or auto-post. One thoughtful post per relevant community.
- Respond to questions and issues; that's what sustains a project.
