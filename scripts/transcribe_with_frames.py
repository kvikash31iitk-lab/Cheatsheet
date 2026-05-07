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
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

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
FRAME_RESOLUTION = 720
DEDUPE_HAMMING_THRESHOLD = 6
JPEG_QUALITY = 4

CHUNK_SECONDS = 8 * 60
INTER_CALL_DELAY = 15.0
CHUNK_RETRY_ATTEMPTS = 8
CHUNK_RETRY_WAIT = 240.0
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


def _ytdlp_base() -> list[str]:
    """yt-dlp command prefix, with --cookies appended if a cookies file exists.

    Cookies file location is configurable via ``YT_COOKIES_PATH`` (env var). On
    a VPS where YouTube returns *"Sign in to confirm you're not a bot"*, dropping
    a Netscape-format cookies.txt at that path lets yt-dlp authenticate as your
    logged-in browser session and bypass the challenge.
    """
    import os
    cmd = ["yt-dlp"]
    cookies_path = os.environ.get("YT_COOKIES_PATH", "/home/botuser/cookies.txt")
    if cookies_path and Path(cookies_path).exists():
        cmd += ["--cookies", cookies_path]
    return cmd


def fetch_metadata(url: str) -> dict:
    """Return {'id', 'title', 'duration'} via yt-dlp --print.

    Uses three separate ``--print`` flags so each field is on its own line —
    avoids brittle separator parsing when titles contain pipes / tabs / etc.
    """
    cmd = _ytdlp_base() + ["--skip-download", "--no-playlist",
           "--print", "%(id)s",
           "--print", "%(title)s",
           "--print", "%(duration)s",
           url]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed:\n{p.stderr}")
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if len(lines) < 3:
        raise RuntimeError(f"unexpected yt-dlp output: {p.stdout!r}")
    # Last 3 non-empty lines are id, title, duration (warnings come before).
    vid, title, duration = lines[-3], lines[-2], lines[-1]
    try:
        duration_f = float(duration or 0)
    except ValueError:
        raise RuntimeError(
            f"yt-dlp returned non-numeric duration {duration!r}; "
            f"full output:\n{p.stdout}")
    return {"id": vid.strip(), "title": title.strip(), "duration": duration_f}


def ensure_audio(url: str, work: Path, on_progress: ProgressFn = None) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    audio_full = work / "session_full.mp3"
    if audio_full.exists() and audio_full.stat().st_size > 0:
        return audio_full

    raw = work / "raw_audio.m4a"
    if not raw.exists():
        _emit(on_progress, "Downloading audio...")
        cmd = _ytdlp_base() + ["-f", "bestaudio[ext=m4a]/bestaudio",
               "--no-playlist", "-o", str(raw), url]
        if _run(cmd).returncode != 0:
            raise RuntimeError("yt-dlp audio download failed")

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
    cmd = _ytdlp_base() + ["-f", "bestvideo[height<=720][ext=mp4]/best[height<=720]/worst",
           "--no-playlist", "-o", str(raw_video), url]
    if _run(cmd).returncode != 0:
        cmd = _ytdlp_base() + ["-f", "worst", "--no-playlist",
                               "-o", str(raw_video), url]
        if _run(cmd).returncode != 0:
            raise RuntimeError("yt-dlp video download failed")
    return raw_video


def probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    return float(json.loads(p.stdout)["format"]["duration"])


def extract_scene_frames(video: Path, duration: float, frames_dir: Path,
                         on_progress: ProgressFn = None) -> list[tuple[float, Path]]:
    raw_dir = frames_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: scene-change frames with showinfo timestamps.
    if not list(raw_dir.glob("scene_*.jpg")):
        _emit(on_progress, "Scanning for scene changes...")
        scene_log = raw_dir / "scene.log"
        cmd = [
            "ffmpeg", "-hide_banner", "-y", "-i", str(video),
            "-vf", (f"select='gt(scene,{SCENE_THRESHOLD})',showinfo,"
                    f"scale={FRAME_RESOLUTION}:-2"),
            "-vsync", "vfr", "-q:v", str(JPEG_QUALITY),
            str(raw_dir / "scene_%05d.jpg"),
        ]
        with open(scene_log, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stderr=f, stdout=subprocess.DEVNULL)

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
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
            "-vf", f"fps={fps},scale={FRAME_RESOLUTION}:-2",
            "-q:v", str(JPEG_QUALITY), str(raw_dir / "grid_%05d.jpg"),
        ]
        subprocess.run(cmd)

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


def transcribe_chunks(chunks, on_progress: ProgressFn = None):
    backend, api_key = load_api_key()
    if backend != "groq":
        raise RuntimeError(f"Expected groq backend, got {backend}")
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
                    data = _post_whisper(GROQ_ENDPOINT, api_key, GROQ_MODEL, path)
                    break
                except KeyboardInterrupt:
                    raise
                except BaseException as exc:
                    if attempt < CHUNK_RETRY_ATTEMPTS:
                        _emit(on_progress,
                              f"Groq rate-limited; waiting {CHUNK_RETRY_WAIT:.0f}s "
                              f"before retry {attempt+1}/{CHUNK_RETRY_ATTEMPTS}...")
                        time.sleep(CHUNK_RETRY_WAIT)
                    else:
                        raise RuntimeError(f"chunk {i} failed after "
                                           f"{CHUNK_RETRY_ATTEMPTS} attempts: {exc}")
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            used_net = True
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
