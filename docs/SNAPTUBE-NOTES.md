# Case study: architecture of SnapTube 7.70.1 (static analysis)

This note describes the **architecture** of a shipping Android downloader, as
observed by static analysis of its APK. It is commentary and interoperability
research: no proprietary source or decompiled code is reproduced here, and none
of it is included in streamgrab. Class names and version strings are cited as
observed facts; everything else is labelled as inference.

The point is pedagogical — the design is a good illustration of the layered
model streamgrab implements, so it is useful to compare the two.

## Subject and method

| | |
|---|---|
| Artifact | `Click_me_to_install_SnapTube_tube_snaptubeversion.apk` |
| SHA-256 | `f1f8014d9b3d4b92d5668b7094fb6ffd5a25b3a74b95e7180e8666eefbebf030` |
| Package | `com.snaptube.premium` |
| Version | `7.70.1.77003301` |
| SDK | min 21 / target 36 |
| Method | JADX decompilation via REA; class inventory, string scan, reference tracing |
| Runtime | not executed; static observations only |

The APK was never installed or run. Conclusions below are about shipped code
and data, not observed runtime behavior.

## The four layers

### 1. Extraction — an in-house, plugin-based extractor library

The app carries its own extractor framework rather than shelling out to a
general-purpose tool:

- `com.snaptube.extractor.pluginlib.*` — the framework: `ExtractorWrapper`,
  `PluginProvider`, `VideoAudioMuxImpl`, plus models such as `VideoInfo`,
  `Format`, `Formats`, `AudioTrack`, `PlaylistItem`, `YTServerAbrStream` and
  `YouTubePlaybackModel`.
- `com.snaptube.extractor.pluginlib.sites.*` — per-site handlers (`Youtube`,
  `Facebook`, `mobiuspace`, `movietv`).
- `com.snaptube.extractor.pluginlib.youtube.*` — YouTube specifics:
  `YoutubeParsingHelper`, `Parser`, `SabrFormatStrategy`, `VideoDecipherInfo`,
  `YouTubeSignCodeServer`, a `jsextractor` package (`ObjToIntMap`, `Token`,
  `UniqueTag`) and a `potoken` package (`BotGuardPoTokenProvider`,
  `BaseJsPatchPoTokenProvider`).
- `com.snaptube.extractor.pluginlib.youtube.ump.UmpRequestHelper` and
  `com.mobiuspace.youtube.ump.*` — a client for YouTube's UMP/SABR streaming
  protocol (`VideoPlaybackAbrRequest`, `SabrContextUpdate`, `StreamProtectionStatus`, …).
- `com.snaptube.video.videoextractor.*` — a second, rule-driven extractor engine
  with per-site codecs: `InstagramCodec`, `TikTokCodec`, `KwaiCodec`,
  `XVideosCodec`, `FacebookCodec`, `GoogleDriveCodec`, `MobiuspaceVideoExtractor`,
  and models such as `DownloadInfo`, `MpdItem`, `SiteSupportRules`,
  `YoutubeVideoITag`.

**Inference:** extraction is modular and updated independently of the app core
(plugin/site-injection classes such as `SiteInjectCode` and
`BackgroundWebExtractProvider` support this). The YouTube path is substantial
because that site's formats are signed/obfuscated and rate-limited.

**On yt-dlp:** a string in `classes3.dex` reads `yt-dlp` next to
`https://github.com/yt-dlp/yt-dlp/pull/11190` (in the YouTube PO-token area).
That is a reference/citation, **not** a bundled yt-dlp runtime — there is no
Python, no yt-dlp asset, and no `youtube-dl`/NewPipe package in the APK.

### 2. Transfer — a segmented download SDK

The byte-transfer engine is the `com.wandoujia.*` family:

- `com.wandoujia.download.*` — segmented/block transfer with resume:
  `model.DserviceInfo`, `model.DlinkInfo`, `model.SegmentInfo`,
  `model.DownloadSegMetaData`, `model.segments.DownloadBlockInfo`,
  `rpc.SingleThreadBlockDownloadTask`, `rpc.HttpStreamDownloadTask`,
  `rpc.IBlockDownloadTask`, `rpc.InnerDownloadRequest`, and
  `rpc.SabrFormatChangedException`.
- `com.wandoujia.m3u8download.*` — HLS: `MasterPlaylist`, `MediaPlaylist`,
  `MediaSegment`, `Key`, `VariantStream`, `MediaRemuxer`, `MergeStrategy`.
- `com.wandoujia.mtdownload.*` — DASH/MPD (`dashmpd.download.DashMpdException`,
  `Dispatcher`).
- `com.wandoujia.base.*` — shared config, reflection and media utilities.

That these engines are actually wired into the app (not dead code) is supported
by incoming references from the app's own obfuscated classes — e.g. `o.jR0`
→ HLS `MediaRemuxer`, `o.UA1`/`o.aB1` → `SabrFormatChangedException`,
`o.rQ`/`o.sQ`/`o.uQ`/`o.x90` → `DashMpdException`, and `o.C10`/`o.Uv` →
`DownloadBlockInfo`.

**Inference:** one engine covers progressive HTTP, HLS and DASH, with a shared
block/segment model and resume metadata — the same decomposition streamgrab
uses in `downloader.py`, `hls.py` and `dash.py`.

### 3. Muxing — FFmpeg, statically linked

- Java/Kotlin wrappers: `com.snaptube.ffmpeg.*`,
  `com.snaptube.premium.ffmpegkit.*` (`FFmpegKitConfig`, `SessionState`,
  `LogRedirectionStrategy`, `Signal`) and the JNI class
  `com.snaptube.taskManager.ffmpeg.FFmpegHelper` (`ffmpegInit`,
  `ffmpegExecCommand`, `ffmpegMuxesToWebM`, `ffmpegTranscodeTomp3`,
  `ffmpegCancel`, `ffmpegGetErrorMsg`).
- Native payload: `lib/arm64-v8a/libvideo_v1.so` embeds
  **FFmpeg n2.5.11-36-g52a9f668ee** (`Lavc56.13.100`, `Lavf56.15.102`), built with
  a minimal feature set (`--enable-muxer=mp4 --enable-demuxer=mov`,
  `--disable-network`, etc.). `lib/arm64-v8a/libmp3cvt.so` is an AAC→MP3
  converter (Nero AAC decoder symbols `NeAACDec*`).
- `FFmpegHelper.loadLibrary()` loads the `.so` from a downloaded plugin
  directory at runtime, so the media stack can be updated independently.

**Inference:** FFmpeg is used only for container work — muxing separate
video/audio into MP4 and transcoding audio — not for network I/O or decoding
during download. That matches `muxer.py` in streamgrab.

### 4. Playback — AndroidX Media3 / ExoPlayer

`androidx.media3.*` and ExoPlayer classes are present for preview/playback,
separate from the download path.

## Layer mapping: SnapTube → streamgrab

| Concern | SnapTube (observed) | streamgrab (this repo) |
|---|---|---|
| Resolve URL → formats | `extractor.pluginlib`, `video.videoextractor` | `extractor/` (HLS, DASH, direct, generic, yt-dlp bridge) |
| Segmented HTTP + resume | `com.wandoujia.download` | `downloader.py` |
| HLS | `com.wandoujia.m3u8download` | `hls.py` |
| DASH | `com.wandoujia.mtdownload` | `dash.py` |
| Mux / transcode | FFmpeg 2.5.11 (`libvideo_v1.so`) | `muxer.py` (system FFmpeg) |
| Playback | Media3 / ExoPlayer | out of scope |

The convergence is not accidental: it is the natural decomposition of the
problem. streamgrab is an independent implementation of that decomposition, not
a port.

## What was *not* found

- No bundled yt-dlp / youtube-dl / NewPipe runtime.
- No `libffmpeg.so`; FFmpeg is compiled into app-specific libraries.
- No evidence in the static inventory of a generic "download any site" engine
  beyond the plugin/rule systems above.

## Limitations

- Static analysis only; runtime wiring, server-side behavior and dynamic plugin
  loading were not observed.
- Some base classes in the `com.wandoujia.*` family were not resolvable by exact
  name in the decompiler's class inventory (only nested classes appeared), so the
  inventory is partial.
- Manifest intent-filter coverage was partial for the deep-link activity.
- Class names are as reported by the decompiler; obfuscated app classes (`o.*`)
  are not meaningful names.

## Legal note

This document is independent interoperability commentary. It contains no
decompiled source, no assets, and no code from the analyzed application, and it
is not a guide to circumventing any protection. Trademarks and code remain the
property of their owners. Do not use this note to redistribute the analyzed
application or its components.
