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
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

try:
    from scripts.ytdlp_client import invalid_response_error, run_ytdlp
except ModuleNotFoundError:  # Direct execution: python scripts/transcribe_with_frames.py
    from ytdlp_client import invalid_response_error, run_ytdlp

WATCH_SKILL_DIR = Path.home() / ".claude" / "skills" / "watch" / "scripts"
if str(WATCH_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(WATCH_SKILL_DIR))
try:
    from whisper import _post_whisper, GROQ_ENDPOINT, GROQ_MODEL, load_api_key  # noqa: E402
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
MAX_LOCAL_MEDIA_SECONDS = 2 * 60 * 60
LOCAL_MEDIA_PROBE_TIMEOUT_SECONDS = 30.0
LOCAL_MEDIA_FFMPEG_TIMEOUT_SECONDS = 30 * 60.0
LOCAL_MEDIA_PROTOCOL_WHITELIST = "file,crypto,data"
# ============================================================================

ProgressFn = Optional[Callable[[str], None]]
YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})")


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


def ensure_audio(url: str, work: Path, on_progress: ProgressFn = None) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    audio_full = work / "session_full.mp3"
    if audio_full.exists() and audio_full.stat().st_size > 0:
        return audio_full

    raw = work / "raw_audio.m4a"
    if not raw.exists():
        _emit(on_progress, "Downloading audio...")
        run_ytdlp(
            [
                "-f", "bestaudio[ext=m4a]/bestaudio",
                "--no-playlist", "-o", str(raw), url,
            ],
            operation="download audio",
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
    run_ytdlp(
        [
            "-f", "bestvideo[height<=720][ext=mp4]/best[height<=720]/worst",
            "--no-playlist", "-o", str(raw_video), url,
        ],
        operation="download video",
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
                        on_progress: ProgressFn = None) -> Path:
    """Transcode validated local media to the pipeline's canonical MP3."""
    audio_full = work / "session_full.mp3"
    if audio_full.exists() and audio_full.stat().st_size > 0:
        return audio_full

    _emit(on_progress, "Encoding uploaded media for Whisper...")
    temporary = work / "session_full.tmp.mp3"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-protocol_whitelist", LOCAL_MEDIA_PROTOCOL_WHITELIST,
        "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "64k", str(temporary),
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
    temporary.replace(audio_full)
    return audio_full


def extract_scene_frames(video: Path, duration: float, frames_dir: Path,
                         on_progress: ProgressFn = None, *,
                         local_only: bool = False) -> list[tuple[float, Path]]:
    raw_dir = frames_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_options = []
    run_options = {}
    if local_only:
        input_options = [
            "-nostdin", "-protocol_whitelist", LOCAL_MEDIA_PROTOCOL_WHITELIST,
        ]
        run_options["timeout"] = LOCAL_MEDIA_FFMPEG_TIMEOUT_SECONDS

    # Pass 1: scene-change frames with showinfo timestamps.
    if not list(raw_dir.glob("scene_*.jpg")):
        _emit(on_progress, "Scanning for scene changes...")
        scene_log = raw_dir / "scene.log"
        cmd = [
            "ffmpeg", "-hide_banner", "-y", *input_options, "-i", str(video),
            "-vf", (f"select='gt(scene,{SCENE_THRESHOLD})',showinfo,"
                    f"scale='min(iw,{FRAME_RESOLUTION})':-2:flags=lanczos"),
            "-vsync", "vfr", "-q:v", str(JPEG_QUALITY),
            str(raw_dir / "scene_%05d.jpg"),
        ]
        with open(scene_log, "w", encoding="utf-8") as f:
            try:
                subprocess.run(
                    cmd, stderr=f, stdout=subprocess.DEVNULL, **run_options
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Timed out while extracting local frames") from exc

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
            "-vf", f"fps={fps},scale='min(iw,{FRAME_RESOLUTION})':-2:flags=lanczos",
            "-q:v", str(JPEG_QUALITY), str(raw_dir / "grid_%05d.jpg"),
        ]
        try:
            subprocess.run(cmd, **run_options)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Timed out while sampling local frames") from exc

    grid_files = sorted(raw_dir.glob("grid_*.jpg"))
    grid_times = [i * FALLBACK_INTERVAL_S for i in range(len(grid_files))]

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

    backend_, api_key = load_api_key()
    if backend_ != "groq":
        raise RuntimeError(f"Expected groq backend, got {backend_}")

    def _do(path):
        return _post_whisper(GROQ_ENDPOINT, api_key, GROQ_MODEL, path)

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
    """Run download → (frame extraction) → audio chunking → transcription.

    Returns a dict with paths and metadata. Idempotent: re-running with the
    same `work` directory reuses cached intermediates.
    """
    work = Path(work); work.mkdir(parents=True, exist_ok=True)

    meta = fetch_metadata(url)
    audio = ensure_audio(url, work, on_progress=on_progress)

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

    chunks = split_audio(audio, work, on_progress=on_progress)
    segments = transcribe_chunks(chunks, on_progress=on_progress)
    outputs = write_outputs(segments, work, frames_index_data)

    return {
        "video_id": meta["id"],
        "title": meta["title"],
        "duration_seconds": meta["duration"],
        "transcript_txt": outputs["transcript_txt"],
        "transcript_json": outputs["transcript_json"],
        "transcript_with_frames": outputs["transcript_with_frames"],
        "frames_dir": frames_dir,
        "frames_index": frames_index_path,
        "frames_count": len(frames_index_data) if frames_index_data else 0,
        "segments_count": len(segments),
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
        audio = _ensure_local_audio(media_path, work, on_progress=on_progress)
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
