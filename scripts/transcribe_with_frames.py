"""Transcribe a YouTube video and (optionally) extract a curated set of frames.

This module is dual-purpose:

  - As a script: edit the constants at the bottom and run
        python transcribe_with_frames.py
  - As a library: ``from transcribe_with_frames import run_pipeline``
        run_pipeline(url, work_dir, extract_frames=True, on_progress=cb)

The bot worker uses the library form. The standalone form is preserved for
quick one-off runs.

Frame extraction is scene-aware (ffmpeg's scene-change detector) plus a
fallback grid (one frame every FALLBACK_INTERVAL_S), then deduplicated by
perceptual hash so the surviving set captures real visual events.
"""
from __future__ import annotations

import json
import html
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from scripts.ytdlp_client import (
        YtDlpError,
        configured_proxies,
        invalid_response_error,
        run_ytdlp,
        run_ytdlp_profiles,
        youtube_client_profiles,
    )
except ModuleNotFoundError:  # Direct execution: python scripts/transcribe_with_frames.py
    from ytdlp_client import (
        YtDlpError,
        configured_proxies,
        invalid_response_error,
        run_ytdlp,
        run_ytdlp_profiles,
        youtube_client_profiles,
    )

WATCH_SKILL_DIR = Path.home() / ".claude" / "skills" / "watch" / "scripts"
if str(WATCH_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(WATCH_SKILL_DIR))
try:
    from whisper import GROQ_MODEL, load_api_key  # noqa: E402
except ImportError as exc:
    raise SystemExit(
        f"Could not import whisper client from {WATCH_SKILL_DIR}.\n"
        "Run: git clone https://github.com/bradautomates/claude-video.git "
        "~/.claude/skills/watch"
    ) from exc

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# ============================================================================
# Tunable constants (apply to both library and standalone use)
# ============================================================================
SCENE_THRESHOLD = 0.30
FALLBACK_INTERVAL_S = 60
# Max width in pixels for an extracted frame. The scale filter caps at this
# value via min(iw, FRAME_RESOLUTION) so we never *upscale* a low-res source
# (which doesn't add real detail and just blurs). For 1080p YouTube tutorials
# this gives a sharp 1280-wide frame that comfortably exceeds 200 DPI when
# ReportLab embeds it at ~5 inches on A4.
FRAME_RESOLUTION = 1280
DEDUPE_HAMMING_THRESHOLD = 6
# ffmpeg `-q:v` for MJPEG: 1=visually lossless, 31=worst. 2 is the standard
# "transparent quality" choice — no visible artifacts on text/UI screenshots
# while keeping file size ~2x smaller than q=1. Was 4 (clearly lossy on code
# editors / slide text).
JPEG_QUALITY = 2

CHUNK_SECONDS = 8 * 60
INTER_CALL_DELAY = 15.0
CHUNK_RETRY_ATTEMPTS = 8
CHUNK_RETRY_WAIT = 240.0
CAPTION_CONNECT_TIMEOUT_SECONDS = 8.0
CAPTION_READ_TIMEOUT_SECONDS = 20.0
MAX_LOCAL_MEDIA_SECONDS = 2 * 60 * 60
LOCAL_MEDIA_PROBE_TIMEOUT_SECONDS = 30.0
LOCAL_MEDIA_FFMPEG_TIMEOUT_SECONDS = 30 * 60.0
LOCAL_MEDIA_PROTOCOL_WHITELIST = "file,crypto,data"
LOCAL_MEDIA_FORMAT_WHITELIST = "mov,matroska,webm,mp3,wav,ogg,flac,aac"
MAX_LOCAL_VIDEO_DIMENSION = 8192
MAX_LOCAL_VIDEO_PIXELS = 33_554_432
MAX_LOCAL_SCENE_FRAMES = 360
MAX_LOCAL_GRID_FRAMES = MAX_LOCAL_MEDIA_SECONDS // FALLBACK_INTERVAL_S + 1
# ============================================================================

ProgressFn = Optional[Callable[[str], None]]
YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})")


def extract_video_id(url: str) -> str:
    m = YOUTUBE_ID_RE.search(url)
    if not m:
        raise ValueError(f"Could not extract video ID from URL: {url}")
    return m.group(1)


def _emit(on_progress: ProgressFn, msg: str) -> None:
    if on_progress:
        try:
            on_progress(msg)
        except Exception:
            pass
    print(msg, flush=True)


def _run(cmd: list[str], **kw):
    print(f"[run] {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}", flush=True)
    return subprocess.run(cmd, **kw)


def fetch_metadata(url: str) -> dict:
    """Return {'id', 'title', 'duration'} via yt-dlp --print.

    Uses three separate ``--print`` flags so each field is on its own line —
    avoids brittle separator parsing when titles contain pipes / tabs / etc.
    """
    p = run_ytdlp(
        [
            "--skip-download", "--no-playlist",
            "--print", "%(id)s",
            "--print", "%(title)s",
            "--print", "%(duration)s",
            url,
        ],
        operation="read video information",
    )
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if len(lines) < 3:
        raise invalid_response_error(
            "read video information",
            f"Expected id/title/duration lines; output was:\n{p.stdout}",
        )
    # Last 3 non-empty lines are id, title, duration (warnings come before).
    vid, title, duration = lines[-3], lines[-2], lines[-1]
    try:
        duration_f = float(duration or 0)
    except ValueError:
        raise invalid_response_error(
            "read video information",
            f"Non-numeric duration {duration!r}; output was:\n{p.stdout}",
        )
    return {"id": vid.strip(), "title": title.strip(), "duration": duration_f}


def fetch_metadata_resilient(url: str, on_progress: ProgressFn = None) -> dict:
    """Fetch metadata across extractor clients, with a usable URL-only fallback."""

    video_id = extract_video_id(url)
    # oEmbed is a lightweight public metadata path.  It avoids invoking the
    # media extractor merely to obtain a title, and therefore keeps a
    # caption-first job independent from downloadable YouTube formats.
    try:
        endpoint = "https://www.youtube.com/oembed?" + urlencode(
            {
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            }
        )
        request = Request(endpoint, headers={"User-Agent": "YTsummary/1.0"})
        with urlopen(request, timeout=15) as response:
            raw = response.read(128 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        title = str(payload.get("title") or "").strip()
        if title:
            return {"id": video_id, "title": title, "duration": 0.0}
    except Exception:
        _emit(on_progress, "Lightweight title lookup unavailable; trying extractor metadata...")
    try:
        p = run_ytdlp_profiles(
            [
                "--skip-download", "--no-playlist",
                "--print", "%(id)s",
                "--print", "%(title)s",
                "--print", "%(duration)s",
                url,
            ],
            operation="read video information",
            on_profile=lambda name, index, total: _emit(
                on_progress,
                f"Metadata route {index}/{total}: {name}",
            ),
        )
        lines = [line for line in p.stdout.splitlines() if line.strip()]
        if len(lines) >= 3:
            try:
                duration = float(lines[-1] or 0)
            except ValueError:
                duration = 0.0
            return {
                "id": lines[-3].strip() or video_id,
                "title": lines[-2].strip(),
                "duration": duration,
            }
    except YtDlpError as exc:
        _emit(
            on_progress,
            "Metadata lookup was blocked; continuing with transcript-derived "
            f"metadata ({exc.kind.value}).",
        )
    return {"id": video_id, "title": f"YouTube video {video_id}", "duration": 0.0}


def _clean_caption_text(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _caption_segments_from_items(items) -> list[dict]:
    segments: list[dict] = []
    previous = ""
    for item in items:
        if isinstance(item, dict):
            text = item.get("text", "")
            start = item.get("start", 0.0)
            duration = item.get("duration", 0.0)
        else:
            text = getattr(item, "text", "")
            start = getattr(item, "start", 0.0)
            duration = getattr(item, "duration", 0.0)
        clean = _clean_caption_text(str(text or ""))
        if not clean or clean == previous:
            continue
        previous = clean
        start_f = max(0.0, float(start or 0.0))
        duration_f = max(0.0, float(duration or 0.0))
        segments.append({
            "start": round(start_f, 2),
            "end": round(start_f + duration_f, 2),
            "chunk": int(start_f // CHUNK_SECONDS) + 1,
            "text": clean,
        })
    return segments


def _caption_segments_are_useful(segments: list[dict]) -> bool:
    text_chars = sum(len(segment.get("text", "")) for segment in segments)
    return bool(segments) and text_chars >= 40


def _api_for_proxy(proxy: str | None):
    import requests
    from youtube_transcript_api import YouTubeTranscriptApi

    class _TimeoutSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs.setdefault(
                "timeout",
                (CAPTION_CONNECT_TIMEOUT_SECONDS, CAPTION_READ_TIMEOUT_SECONDS),
            )
            return super().request(method, url, **kwargs)

    session = _TimeoutSession()

    if not proxy:
        return YouTubeTranscriptApi(http_client=session)
    from youtube_transcript_api.proxies import GenericProxyConfig

    return YouTubeTranscriptApi(
        proxy_config=GenericProxyConfig(http_url=proxy, https_url=proxy),
        http_client=session,
    )


def _fetch_captions_with_transcript_api(video_id: str) -> list[dict]:
    """Fetch the best caption track, accepting English, Hindi, and Hinglish tracks directly."""

    routes: list[str | None] = [None]
    try:
        routes.extend(configured_proxies())
    except Exception:
        pass
    last_error: Exception | None = None
    for proxy in dict.fromkeys(routes):
        try:
            api = _api_for_proxy(proxy)
            tracks = list(api.list(video_id))
            if not tracks:
                return []
            
            # Prioritize tracks: 1. English, 2. Hindi / Hinglish, 3. Any available track
            english = [
                track for track in tracks
                if str(getattr(track, "language_code", "")).lower().startswith("en")
            ]
            hindi = [
                track for track in tracks
                if str(getattr(track, "language_code", "")).lower().startswith("hi")
            ]
            
            pool = english or hindi or tracks
            selected = next(
                (track for track in pool if not getattr(track, "is_generated", True)),
                pool[0],
            )
            return _caption_segments_from_items(selected.fetch())
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []



def _parse_json3_caption(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        text = "".join(
            str(segment.get("utf8") or "")
            for segment in event.get("segs") or []
            if isinstance(segment, dict)
        )
        start = float(event.get("tStartMs") or 0.0) / 1000.0
        duration = float(event.get("dDurationMs") or 0.0) / 1000.0
        rows.append({"text": text, "start": start, "duration": duration})
    return _caption_segments_from_items(rows)


def _fetch_captions_with_ytdlp(
    url: str,
    work: Path,
    on_progress: ProgressFn = None,
) -> list[dict]:
    caption_dir = work / "captions"
    caption_dir.mkdir(parents=True, exist_ok=True)
    output_template = caption_dir / "caption.%(language)s.%(ext)s"
    for index, (name, profile_args) in enumerate(youtube_client_profiles(), 1):
        _emit(on_progress, f"Caption route {index}: yt-dlp {name}")
        try:
            run_ytdlp(
                [
                    *profile_args,
                    "--skip-download", "--no-playlist",
                    "--write-subs", "--write-auto-subs",
                    "--sub-langs", "en.*,hi.*,hi,en,-live_chat",
                    "--sub-format", "json3",
                    "-o", str(output_template),
                    url,

                ],
                operation=f"download captions ({name} client)",
            )
        except YtDlpError:
            continue
        for path in sorted(caption_dir.glob("caption*.json3")):
            try:
                segments = _parse_json3_caption(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if _caption_segments_are_useful(segments):
                return segments
    return []


def try_caption_transcript(
    url: str,
    work: Path,
    on_progress: ProgressFn = None,
) -> dict | None:
    """Try lightweight captions before downloading and transcribing media."""

    video_id = extract_video_id(url)
    transcript_path = work / "transcript.txt"
    transcript_json = work / "transcript.json"
    if transcript_path.exists() and transcript_path.stat().st_size > 40:
        return {
            "transcript_txt": transcript_path,
            "transcript_json": transcript_json if transcript_json.exists() else None,
            "transcript_with_frames": None,
            "provider": "cache",
        }

    _emit(on_progress, "Trying YouTube caption API before media download...")
    segments: list[dict] = []
    provider = "youtube_transcript_api"
    try:
        segments = _fetch_captions_with_transcript_api(video_id)
    except Exception as exc:
        _emit(
            on_progress,
            f"Caption API unavailable ({type(exc).__name__}); trying yt-dlp captions...",
        )
    if not _caption_segments_are_useful(segments):
        provider = "yt_dlp_captions"
        segments = _fetch_captions_with_ytdlp(url, work, on_progress)
    if not _caption_segments_are_useful(segments):
        _emit(on_progress, "No usable captions found; falling back to local audio transcription.")
        return None

    outputs = write_outputs(segments, work, None)
    _emit(on_progress, f"Using {provider.replace('_', ' ')} ({len(segments)} segments).")
    return {**outputs, "provider": provider, "segments": segments}


def ensure_audio(url: str, work: Path, on_progress: ProgressFn = None) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    audio_full = work / "session_full.mp3"
    if audio_full.exists() and audio_full.stat().st_size > 0:
        return audio_full

    raw = work / "raw_audio.m4a"
    if not raw.exists():
        _emit(on_progress, "Downloading audio...")
        run_ytdlp_profiles(
            [
                "--continue",
                "-f", "bestaudio[ext=m4a]/bestaudio/best[height<=360]/18",
                "--no-playlist", "-o", str(raw), url,
            ],
            operation="download audio",
            on_profile=lambda name, index, total: _emit(
                on_progress,
                f"Audio route {index}/{total}: {name}",
            ),
        )

    _emit(on_progress, "Encoding audio for Whisper...")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(raw), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
           str(audio_full)]
    if _run(cmd).returncode != 0:
        raise RuntimeError("ffmpeg audio encode failed")
    return audio_full


def ensure_video(url: str, work: Path, on_progress: ProgressFn = None) -> Path:
    raw_video = work / "raw_video.mp4"
    if raw_video.exists() and raw_video.stat().st_size > 0:
        return raw_video
    _emit(on_progress, "Downloading video for frame extraction...")
    run_ytdlp_profiles(
        [
            "--continue",
            "-f", "bestvideo[height<=720][ext=mp4]/best[height<=720]/worst",
            "--no-playlist", "-o", str(raw_video), url,
        ],
        operation="download video",
        on_profile=lambda name, index, total: _emit(
            on_progress,
            f"Video route {index}/{total}: {name}",
        ),
    )
    return raw_video


def probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    return float(json.loads(p.stdout)["format"]["duration"])


def _probe_local_media(path: Path) -> dict:
    """Validate a local media file and return its stream metadata."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Local media file does not exist: {path}")
    if path.stat().st_size <= 0:
        raise ValueError("Local media file is empty")

    cmd = [
        "ffprobe", "-v", "error",
        "-protocol_whitelist", LOCAL_MEDIA_PROTOCOL_WHITELIST,
        "-format_whitelist", LOCAL_MEDIA_FORMAT_WHITELIST,
        "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=LOCAL_MEDIA_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is required to process uploaded media") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Timed out while validating local media") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"Local media is not readable by ffprobe{suffix}")

    try:
        payload = json.loads(result.stdout or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("ffprobe returned invalid metadata for local media") from exc
    if not isinstance(payload, dict):
        raise ValueError("ffprobe returned invalid metadata for local media")
    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    streams = [stream for stream in streams if isinstance(stream, dict)]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if not audio_streams:
        raise ValueError("Local media does not contain a playable audio stream")
    for stream in video_streams:
        try:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
        except (TypeError, ValueError):
            raise ValueError("Local video has invalid frame dimensions")
        if (
            width < 0
            or height < 0
            or width > MAX_LOCAL_VIDEO_DIMENSION
            or height > MAX_LOCAL_VIDEO_DIMENSION
            or width * height > MAX_LOCAL_VIDEO_PIXELS
        ):
            raise ValueError("Local video frame dimensions exceed the safe limit")

    format_data = payload.get("format")
    if not isinstance(format_data, dict):
        format_data = {}
    duration_values = [format_data.get("duration")]
    duration_values.extend(stream.get("duration") for stream in audio_streams)
    duration = 0.0
    for raw_duration in duration_values:
        try:
            candidate = float(raw_duration)
        except (TypeError, ValueError):
            continue
        if math.isfinite(candidate) and candidate > duration:
            duration = candidate
    if duration <= 0:
        raise ValueError("Local media audio has no playable duration")
    if duration > MAX_LOCAL_MEDIA_SECONDS:
        raise ValueError(
            f"Local media exceeds the {MAX_LOCAL_MEDIA_SECONDS // 3600}-hour limit"
        )

    return {
        "duration": duration,
        "has_audio": True,
        "has_video": bool(video_streams),
    }


def _ensure_local_audio(media_path: Path, work: Path,
                        on_progress: ProgressFn = None, *,
                        duration_limit: float | None = None) -> Path:
    """Transcode validated local media to the pipeline's canonical MP3."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    audio_full = work / "session_full.mp3"
    if audio_full.exists() and audio_full.stat().st_size > 0:
        return audio_full

    _emit(on_progress, "Encoding uploaded media for Whisper...")
    temporary = work / "session_full.tmp.mp3"
    safe_duration = min(
        float(MAX_LOCAL_MEDIA_SECONDS),
        max(1.0, float(duration_limit or MAX_LOCAL_MEDIA_SECONDS)) + 5.0,
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-protocol_whitelist", LOCAL_MEDIA_PROTOCOL_WHITELIST,
        "-format_whitelist", LOCAL_MEDIA_FORMAT_WHITELIST,
        "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "64k", "-t", f"{safe_duration:.3f}", str(temporary),
    ]
    try:
        result = _run(
            cmd, capture_output=True, text=True,
            timeout=LOCAL_MEDIA_FFMPEG_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to process uploaded media") from exc
    except subprocess.TimeoutExpired as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Timed out while decoding uploaded audio") from exc
    output_missing = not temporary.exists() or temporary.stat().st_size <= 0
    if result.returncode != 0 or output_missing:
        temporary.unlink(missing_ok=True)
        detail = (result.stderr or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"ffmpeg could not decode the uploaded audio{suffix}")
    max_audio_bytes = int(safe_duration * 64_000 / 8 * 1.5) + 1_048_576
    if temporary.stat().st_size > max_audio_bytes:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Decoded uploaded audio exceeds the safe size limit")
    temporary.replace(audio_full)
    return audio_full


def extract_scene_frames(video: Path, duration: float, frames_dir: Path,
                         on_progress: ProgressFn = None, *,
                         local_only: bool = False) -> list[tuple[float, Path]]:
    raw_dir = frames_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_options = []
    run_options = {}
    scene_limit_options = []
    grid_limit_options = []
    duration_limit_options = []
    if local_only:
        input_options = [
            "-nostdin", "-protocol_whitelist", LOCAL_MEDIA_PROTOCOL_WHITELIST,
            "-format_whitelist", LOCAL_MEDIA_FORMAT_WHITELIST,
        ]
        run_options["timeout"] = LOCAL_MEDIA_FFMPEG_TIMEOUT_SECONDS
        scene_limit_options = ["-frames:v", str(MAX_LOCAL_SCENE_FRAMES)]
        grid_limit_options = ["-frames:v", str(MAX_LOCAL_GRID_FRAMES)]
        duration_limit_options = [
            "-t",
            f"{min(MAX_LOCAL_MEDIA_SECONDS, max(1.0, duration) + 5.0):.3f}",
        ]

    # Pass 1: scene-change frames with showinfo timestamps.
    if not list(raw_dir.glob("scene_*.jpg")):
        _emit(on_progress, "Scanning for scene changes...")
        scene_log = raw_dir / "scene.log"
        cmd = [
            "ffmpeg", "-hide_banner", "-y", *input_options, "-i", str(video),
            *duration_limit_options,
            "-vf", (f"select='gt(scene,{SCENE_THRESHOLD})',showinfo,"
                    f"scale='min(iw,{FRAME_RESOLUTION})':-2:flags=lanczos"),
            "-vsync", "vfr", "-q:v", str(JPEG_QUALITY),
            "-pix_fmt", "yuvj420p",
            *scene_limit_options,
            str(raw_dir / "scene_%05d.jpg"),
        ]
        with open(scene_log, "w", encoding="utf-8") as f:
            try:
                result = subprocess.run(
                    cmd, stderr=f, stdout=subprocess.DEVNULL, **run_options
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Timed out while extracting local frames") from exc
        if local_only and result.returncode != 0:
            raise RuntimeError("ffmpeg could not extract uploaded video frames")

    scene_times: list[float] = []
    log_path = raw_dir / "scene.log"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "pts_time:" in line and "showinfo" in line.lower():
                try:
                    scene_times.append(float(line.split("pts_time:")[1].split()[0]))
                except (ValueError, IndexError):
                    pass
    scene_files = sorted(raw_dir.glob("scene_*.jpg"))
    if len(scene_times) != len(scene_files) and scene_files:
        n = len(scene_files)
        scene_times = [duration * (i + 0.5) / n for i in range(n)]

    # Pass 2: fallback grid.
    if not list(raw_dir.glob("grid_*.jpg")):
        _emit(on_progress, "Sampling fallback frames...")
        fps = 1.0 / FALLBACK_INTERVAL_S
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            *input_options, "-i", str(video),
            *duration_limit_options,
            "-vf", f"fps={fps},scale='min(iw,{FRAME_RESOLUTION})':-2:flags=lanczos",
            "-q:v", str(JPEG_QUALITY), "-pix_fmt", "yuvj420p",
            *grid_limit_options,
            str(raw_dir / "grid_%05d.jpg"),
        ]
        try:
            result = subprocess.run(cmd, **run_options)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Timed out while sampling local frames") from exc
        if local_only and result.returncode != 0:
            raise RuntimeError("ffmpeg could not sample uploaded video frames")

    grid_files = sorted(raw_dir.glob("grid_*.jpg"))
    grid_times = [i * FALLBACK_INTERVAL_S for i in range(len(grid_files))]

    # Very short or visually static videos may produce neither a scene-change
    # frame nor a 60-second grid sample. Always capture one midpoint frame so
    # Book Notes does not silently become an image-free document.
    if not scene_files and not grid_files and duration > 0:
        _emit(on_progress, "Capturing a representative frame...")
        representative = raw_dir / "grid_00001.jpg"
        midpoint = max(0.0, duration / 2.0)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            *input_options, "-ss", f"{midpoint:.3f}", "-i", str(video),
            "-frames:v", "1",
            "-vf", f"scale='min(iw,{FRAME_RESOLUTION})':-2:flags=lanczos",
            "-q:v", str(JPEG_QUALITY), "-pix_fmt", "yuvj420p",
            str(representative),
        ]
        try:
            result = subprocess.run(cmd, **run_options)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Timed out while capturing an uploaded video frame"
            ) from exc
        if local_only and result.returncode != 0:
            raise RuntimeError(
                "ffmpeg could not capture an uploaded video frame"
            )
        if representative.exists():
            grid_files = [representative]
            grid_times = [midpoint]

    all_frames = list(zip(scene_times, scene_files)) + list(zip(grid_times, grid_files))
    all_frames.sort(key=lambda x: x[0])
    return all_frames


def dedupe_frames(candidates: list[tuple[float, Path]],
                  on_progress: ProgressFn = None) -> list[tuple[float, Path]]:
    try:
        from PIL import Image
        import imagehash
    except ImportError:
        return candidates
    _emit(on_progress, f"Deduplicating {len(candidates)} candidate frames...")
    kept: list[tuple[float, Path, "imagehash.ImageHash"]] = []
    for ts, path in candidates:
        try:
            with Image.open(path) as im:
                h = imagehash.phash(im)
        except Exception:
            continue
        if kept and (h - kept[-1][2]) < DEDUPE_HAMMING_THRESHOLD:
            continue
        kept.append((ts, path, h))
    return [(ts, p) for ts, p, _ in kept]


def write_final_frames(kept: list[tuple[float, Path]], frames_dir: Path,
                       frames_index: Path) -> list[dict]:
    index: list[dict] = []
    for ts, src in kept:
        h, rem = divmod(int(ts), 3600)
        m, s = divmod(rem, 60)
        name = f"frame_{h:02d}-{m:02d}-{s:02d}.jpg"
        dst = frames_dir / name
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
        index.append({"timestamp": round(ts, 2), "file": name})
    frames_index.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def split_audio(audio: Path, work: Path, on_progress: ProgressFn = None
                ) -> list[tuple[Path, float, float]]:
    duration = probe_duration(audio)
    _emit(on_progress, f"Splitting {duration/60:.1f} min of audio into chunks...")
    chunks: list[tuple[Path, float, float]] = []
    n, start = 0, 0.0
    while start < duration:
        end = min(start + CHUNK_SECONDS, duration)
        n += 1
        cp = work / f"chunk_{n:02d}.mp3"
        if cp.exists():
            chunks.append((cp, start, end)); start = end; continue
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(audio),
               "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k",
               str(cp)]
        if subprocess.run(cmd).returncode != 0:
            raise RuntimeError(f"chunk split failed at {n}")
        chunks.append((cp, start, end)); start = end
    return chunks


def _make_whisper_runner():
    """Returns ``(transcribe_fn, is_local)`` for the configured backend.

    ``WHISPER_BACKEND=local`` selects the on-VPS faster-whisper runner;
    anything else (or unset) keeps the original Groq Whisper path.
    """
    import os as _os

    backend = (_os.environ.get("WHISPER_BACKEND") or "groq").lower()

    if backend == "local":
        from scripts.whisper_local import transcribe_chunk as _local_transcribe

        def _do(path):
            return _local_transcribe(path)

        return _do, True

    from bot.config import GROQ_API_KEY, GROQ_API_KEYS
    keys_pool = list(dict.fromkeys(GROQ_API_KEYS or [GROQ_API_KEY]))
    if not keys_pool:
        backend_, api_key = load_api_key()
        keys_pool = [api_key]

    from groq import Groq
    clients = [Groq(api_key=k) for k in keys_pool]

    def _do(path):
        source = Path(path)
        last_exc = None
        for client in clients:
            try:
                with source.open("rb") as audio_file:
                    result = client.audio.transcriptions.create(
                        file=(source.name, audio_file.read()),
                        model=GROQ_MODEL,
                        response_format="verbose_json",
                        timestamp_granularities=["segment"],
                        temperature=0.0,
                    )

                segments = []
                for segment in getattr(result, "segments", None) or []:
                    if isinstance(segment, dict):
                        start = segment.get("start", 0.0)
                        end = segment.get("end", 0.0)
                        text = segment.get("text", "")
                    else:
                        start = getattr(segment, "start", 0.0)
                        end = getattr(segment, "end", 0.0)
                        text = getattr(segment, "text", "")
                    segments.append(
                        {
                            "start": float(start or 0.0),
                            "end": float(end or 0.0),
                            "text": str(text or ""),
                        }
                    )
                return {
                    "text": str(getattr(result, "text", "") or ""),
                    "segments": segments,
                }
            except Exception as exc:
                last_exc = exc
                err_s = str(exc).lower()
                if "429" in err_s or "quota" in err_s or "rate limit" in err_s:
                    continue
                raise exc
        raise RuntimeError(f"All Groq Whisper API keys failed. Last error: {last_exc}")

    return _do, False



def transcribe_chunks(chunks, on_progress: ProgressFn = None):
    transcribe_one, is_local = _make_whisper_runner()
    all_segments = []
    total = len(chunks)
    for i, (path, start_offset, _end) in enumerate(chunks, 1):
        cache = path.with_suffix(".json")
        used_net = False
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
        else:
            _emit(on_progress, f"Transcribing chunk {i}/{total}...")
            data = None
            for attempt in range(1, CHUNK_RETRY_ATTEMPTS + 1):
                try:
                    data = transcribe_one(path)
                    break
                except KeyboardInterrupt:
                    raise
                except BaseException as exc:
                    # Local whisper failures are usually fatal (OOM, bad audio)
                    # so don't waste 4 minutes per retry.
                    if is_local or attempt >= CHUNK_RETRY_ATTEMPTS:
                        raise RuntimeError(
                            f"chunk {i} failed after "
                            f"{attempt} attempts: {exc}"
                        )
                    _emit(
                        on_progress,
                        f"Groq rate-limited; waiting {CHUNK_RETRY_WAIT:.0f}s "
                        f"before retry {attempt+1}/{CHUNK_RETRY_ATTEMPTS}...",
                    )
                    time.sleep(CHUNK_RETRY_WAIT)
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            used_net = not is_local
        for seg in data.get("segments") or []:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            all_segments.append({
                "start": round(float(seg.get("start") or 0.0) + start_offset, 2),
                "end": round(float(seg.get("end") or 0.0) + start_offset, 2),
                "chunk": i,
                "text": text,
            })
        # Only throttle between chunks for the rate-limited Groq path —
        # local whisper has no throttle reason to wait.
        if i < len(chunks) and used_net:
            time.sleep(INTER_CALL_DELAY)
    return all_segments


def write_outputs(segments: list[dict], work: Path,
                  frames_index: list[dict] | None) -> dict:
    out_json = work / "transcript.json"
    out_json.write_text(json.dumps(segments, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    out_txt = work / "transcript.txt"
    lines, last_chunk = [], 0
    for seg in segments:
        if seg["chunk"] != last_chunk:
            lines.append(f"\n## Chunk {seg['chunk']} "
                         f"(~{(seg['chunk']-1)*8}-{seg['chunk']*8} min)\n")
            last_chunk = seg["chunk"]
        m, s = divmod(int(seg["start"]), 60)
        h, m = divmod(m, 60)
        stamp = f"[{h:02d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"
        lines.append(f"{stamp} {seg['text']}")
    out_txt.write_text("\n".join(lines), encoding="utf-8")

    out_combined = None
    if frames_index is not None:
        out_combined = work / "transcript_with_frames.txt"
        events: list[tuple[float, str]] = []
        for seg in segments:
            events.append((seg["start"], f"[{seg['start']:.0f}s] {seg['text']}"))
        for f in frames_index:
            events.append((f["timestamp"], f"        >>> FRAME: {f['file']}"))
        events.sort(key=lambda x: x[0])
        out_combined.write_text("\n".join(t for _, t in events), encoding="utf-8")

    return {"transcript_txt": out_txt, "transcript_json": out_json,
            "transcript_with_frames": out_combined}


def run_pipeline(url: str, work: Path, *, extract_frames: bool = True,
                 on_progress: ProgressFn = None) -> dict:
    """Run captions/media ingestion → optional frames → transcription.

    Returns a dict with paths and metadata. Idempotent: re-running with the
    same `work` directory reuses cached intermediates.  Caption tracks are
    deliberately attempted first because they are faster and do not depend on
    YouTube exposing a downloadable media format.  Media + Whisper remains the
    fallback for videos without useful captions.
    """
    work = Path(work); work.mkdir(parents=True, exist_ok=True)

    caption_result = try_caption_transcript(url, work, on_progress=on_progress)
    meta = fetch_metadata_resilient(url, on_progress=on_progress)

    segments: list[dict] = []
    transcript_provider = "whisper"
    if caption_result:
        transcript_provider = str(caption_result.get("provider") or "captions")
        segments = list(caption_result.get("segments") or [])
        transcript_json = caption_result.get("transcript_json")
        if not segments and transcript_json and Path(transcript_json).exists():
            try:
                payload = json.loads(Path(transcript_json).read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    segments = [row for row in payload if isinstance(row, dict)]
            except (OSError, json.JSONDecodeError):
                segments = []

    frames_index_data = None
    frames_index_path = None
    frames_dir = None
    if extract_frames:
        video = ensure_video(url, work, on_progress=on_progress)
        duration = probe_duration(video)
        frames_dir = work / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames_index_path = work / "frames.json"
        candidates = extract_scene_frames(video, duration, frames_dir,
                                          on_progress=on_progress)
        kept = dedupe_frames(candidates, on_progress=on_progress)
        frames_index_data = write_final_frames(kept, frames_dir, frames_index_path)

    if caption_result:
        if frames_index_data is not None and segments:
            outputs = write_outputs(segments, work, frames_index_data)
        else:
            outputs = {
                "transcript_txt": Path(caption_result["transcript_txt"]),
                "transcript_json": (
                    Path(caption_result["transcript_json"])
                    if caption_result.get("transcript_json")
                    else None
                ),
                "transcript_with_frames": None,
            }
    else:
        audio = ensure_audio(url, work, on_progress=on_progress)
        chunks = split_audio(audio, work, on_progress=on_progress)
        segments = transcribe_chunks(chunks, on_progress=on_progress)
        outputs = write_outputs(segments, work, frames_index_data)

    duration = float(meta.get("duration") or 0.0)
    if duration <= 0 and segments:
        duration = max(float(row.get("end") or row.get("start") or 0.0) for row in segments)

    source_record = {
        "url": url,
        "video_id": meta["id"],
        "title": meta["title"],
        "duration_seconds": duration,
        "transcript_provider": transcript_provider,
        "segments_count": len(segments),
    }
    (work / "source.json").write_text(
        json.dumps(source_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "video_id": meta["id"],
        "title": meta["title"],
        "duration_seconds": duration,
        "transcript_txt": outputs["transcript_txt"],
        "transcript_json": outputs["transcript_json"],
        "transcript_with_frames": outputs["transcript_with_frames"],
        "frames_dir": frames_dir,
        "frames_index": frames_index_path,
        "frames_count": len(frames_index_data) if frames_index_data else 0,
        "segments_count": len(segments),
        "transcript_provider": transcript_provider,
    }


def run_local_media_pipeline(media_path: Path, work: Path, *, title: str,
                             video_id: str, extract_frames: bool = True,
                             transcribe: bool = True,
                             on_progress: ProgressFn = None) -> dict:
    """Run the transcript pipeline from an already-downloaded local file.

    No yt-dlp helper is called on this path. The source must contain decodable
    audio, and frame extraction additionally requires a real video stream.
    With transcribe=False, transcript paths are None and no audio normalization
    or Whisper work is performed.
    """
    media_path = Path(media_path)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)

    _emit(on_progress, "Validating uploaded media...")
    media = _probe_local_media(media_path)
    if extract_frames and not media["has_video"]:
        raise ValueError(
            "Frame extraction requires uploaded media with a video stream"
        )

    frames_index_data = None
    frames_index_path = None
    frames_dir = None
    if extract_frames:
        frames_dir = work / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames_index_path = work / "frames.json"
        candidates = extract_scene_frames(
            media_path, media["duration"], frames_dir,
            on_progress=on_progress, local_only=True,
        )
        kept = dedupe_frames(candidates, on_progress=on_progress)
        frames_index_data = write_final_frames(
            kept, frames_dir, frames_index_path
        )

    segments = []
    outputs = {
        "transcript_txt": None,
        "transcript_json": None,
        "transcript_with_frames": None,
    }
    if transcribe:
        audio = _ensure_local_audio(
            media_path,
            work,
            on_progress=on_progress,
            duration_limit=media["duration"],
        )
        chunks = split_audio(audio, work, on_progress=on_progress)
        segments = transcribe_chunks(chunks, on_progress=on_progress)
        outputs = write_outputs(segments, work, frames_index_data)
    clean_title = str(title or "").strip() or media_path.stem
    clean_video_id = str(video_id or "").strip() or media_path.stem

    return {
        "video_id": clean_video_id,
        "title": clean_title,
        "duration_seconds": media["duration"],
        "transcript_txt": outputs["transcript_txt"],
        "transcript_json": outputs["transcript_json"],
        "transcript_with_frames": outputs["transcript_with_frames"],
        "frames_dir": frames_dir,
        "frames_index": frames_index_path,
        "frames_count": len(frames_index_data) if frames_index_data else 0,
        "segments_count": len(segments),
    }


# ============================================================================
# Standalone runner — original behaviour preserved
# ============================================================================
DEFAULT_URL = "https://www.youtube.com/watch?v=tDGiWn0flK8"
DEFAULT_WORK = Path(r"C:\Users\HP\Documents\Claude\Video notes\work\v1")

if __name__ == "__main__":
    result = run_pipeline(DEFAULT_URL, DEFAULT_WORK, extract_frames=True)
    print(f"\n[done] {result['segments_count']} segments, "
          f"{result['frames_count']} frames")
    print(f"[txt]  {result['transcript_txt']}")
    if result['frames_index']:
        print(f"[idx]  {result['frames_index']}")
