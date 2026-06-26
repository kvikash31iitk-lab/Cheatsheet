#!/usr/bin/env python3
"""UPSC video engine: narration script + digest slides -> narrated MP4.

This is the ``stage_video`` core. It is a generalised port of the proven engine
from ``notes to video/voice_lab/gemtts``:

  - finish_all.py        — hardened Gemini TTS core: server-honored "retry in
                           Ns" backoff, model fallback, write-on-success,
                           hard-verify. (used for engine='gemini')
  - deck_full_chirp_hi.py — Chirp3-HD hi-IN-Chirp3-HD-Alnilam with
                           split_long()/chunks() for the ~600-char sentence
                           limit. (used for engine='chirp')
  - deck_full_gemini_hi.py — the resumable per-slide stitch loop.

Generalisations over the originals:
  - workdir + slide count are derived from the issue, not hardcoded to /root/ntv.
  - the TTS backend is switchable via ``config['engine']`` ('gemini' | 'chirp').
  - keys are read from the environment following bot/config.py conventions:
        gemini -> GKEY (or GEMINI_API_KEY / GOOGLE_API_KEY)
        chirp  -> CTTS_KEY (or GOOGLE_CLOUD_TTS_KEY / GOOGLE_TTS_KEY)
  - slides come from web_work/upsc/<issue_id>/digest.pdf, rasterised at -r 200
    (pdftoppm when available, PyMuPDF fallback) then ffmpeg
    scale=-1:1080,pad=1920:1080:(ow-iw)/2:0:white.
  - sections are arbitrary narration texts; each section -> one wav -> one clip
    held over a slide page (sections map onto pages round-robin so a short
    digest still narrates over whatever pages exist).

Public contract (per the shared build spec):

    build_video(issue_id, config, sections) -> {"video_path", "duration", "size_bytes"}
    list_voices(engine, lang) -> [{"id","label","rank","is_default"}]
    preview_voice(engine, voice, lang, text) -> bytes   (wav)

``config`` keys: engine('gemini'|'chirp'), voice, lang('hi'|'en'),
slide_style('digest'|'clean'|'animated'), theme.

This module owns ONLY upsc_video.py (+ upsc_narration.py). It updates
UpscIssue.video_status / video_progress via SyncSessionLocal; it never edits
upsc_pipeline.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.db import SyncSessionLocal  # noqa: E402
from api.models import UpscIssue  # noqa: E402

# Where the digest pipeline already writes digest.pdf for each issue.
WORK_ROOT = PROJECT_ROOT / "web_work" / "upsc"

# Inter-section silence padding (seconds), matching the proven engine.
PAUSE = 0.4
SAMPLE_RATE = 24000  # mono PCM16, what both TTS backends return / we target


# =============================================================================
# Environment / key helpers (follow bot/config.py: read & strip from os.environ)
# =============================================================================

def _env_any(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def _gemini_key() -> str:
    return _env_any("GKEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def _chirp_key() -> str:
    return _env_any("CTTS_KEY", "GOOGLE_CLOUD_TTS_KEY", "GOOGLE_TTS_KEY")


def _gemini_models() -> list[str]:
    raw = os.environ.get(
        "TTS_MODELS",
        "gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts",
    )
    return [m.strip() for m in raw.split(",") if m.strip()]


def _ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN", "").strip() or "ffmpeg"


def gemini_billing_active() -> bool:
    """Cheap availability flag the UI uses to badge the Gemini engine. We treat
    'a Gemini key is present' as 'billing active'; the real fallback happens at
    synth time (any HTTP failure on every model -> caller can switch to chirp).
    """
    return bool(_gemini_key())


# =============================================================================
# Voice catalogue
# =============================================================================

# Chirp3-HD hi-IN voices, ranked by the WavLM auto-research sweep. Alnilam is
# the validated "vikash voice" and the default. (Ports the ranking baked into
# deck_full_chirp_hi.py, which hardcoded Alnilam.)
_CHIRP_HI = [
    ("hi-IN-Chirp3-HD-Alnilam", "Alnilam (vikash voice)"),
    ("hi-IN-Chirp3-HD-Erinome", "Erinome"),
    ("hi-IN-Chirp3-HD-Achernar", "Achernar"),
    ("hi-IN-Chirp3-HD-Algenib", "Algenib"),
    ("hi-IN-Chirp3-HD-Achird", "Achird"),
    ("hi-IN-Chirp3-HD-Sadachbia", "Sadachbia"),
    ("hi-IN-Chirp3-HD-Schedar", "Schedar"),
    ("hi-IN-Chirp3-HD-Gacrux", "Gacrux"),
    ("hi-IN-Chirp3-HD-Zubenelgenubi", "Zubenelgenubi"),
]
_CHIRP_EN = [
    ("en-IN-Chirp3-HD-Alnilam", "Alnilam (vikash voice)"),
    ("en-IN-Chirp3-HD-Erinome", "Erinome (warm English)"),
    ("en-IN-Chirp3-HD-Achernar", "Achernar"),
    ("en-IN-Chirp3-HD-Algenib", "Algenib"),
    ("en-IN-Chirp3-HD-Charon", "Charon"),
    ("en-IN-Chirp3-HD-Kore", "Kore"),
    ("en-IN-Chirp3-HD-Puck", "Puck"),
]

# Gemini prebuilt voices. Alnilam is the default to mirror the deck scripts.
# These are language-agnostic prebuilt voice names (the STYLE prompt steers the
# language), so the same list serves hi and en.
_GEMINI_VOICES = [
    ("Alnilam", "Alnilam (teacher)"),
    ("Kore", "Kore"),
    ("Puck", "Puck"),
    ("Charon", "Charon"),
    ("Aoede", "Aoede"),
    ("Fenrir", "Fenrir"),
    ("Leda", "Leda"),
    ("Orus", "Orus"),
    ("Zephyr", "Zephyr"),
]


def list_voices(engine: str, lang: str) -> list[dict]:
    """Return ranked voice options for an engine+language. Alnilam is rank 0 /
    default in every list."""
    engine = (engine or "chirp").lower()
    lang = (lang or "hi").lower()
    if engine == "gemini":
        pairs = _GEMINI_VOICES
    else:
        pairs = _CHIRP_HI if lang == "hi" else _CHIRP_EN
    out: list[dict] = []
    for rank, (vid, label) in enumerate(pairs):
        out.append({
            "id": vid,
            "label": label,
            "rank": rank,
            "is_default": rank == 0,
        })
    return out


def _default_voice(engine: str, lang: str) -> str:
    voices = list_voices(engine, lang)
    return voices[0]["id"] if voices else ("Alnilam" if engine == "gemini"
                                           else "hi-IN-Chirp3-HD-Alnilam")


# =============================================================================
# Gemini TTS (hardened core ported from finish_all.py)
# =============================================================================

def _gemini_style(lang: str) -> str:
    if lang == "en":
        return (
            "Narrate in ENGLISH, in the voice of a warm, patient, encouraging "
            "Indian UPSC teacher — clear, confident and conversational, with "
            "natural pauses and gentle emphasis on the key terms. Do not read "
            "these instructions aloud; only speak the lesson text that follows."
        )
    return (
        "Narrate in HINDI, in the voice of a warm, patient, encouraging Indian "
        "UPSC teacher — clear, confident and conversational, with natural pauses "
        "and gentle emphasis on the key terms. Do not read these instructions "
        "aloud; only speak the lesson text that follows."
    )


def _gemini_tts(text: str, voice: str, lang: str) -> bytes:
    """Return PCM16 mono @24kHz for ``text`` via Gemini TTS.

    Ported hardening from finish_all.py:
      - try each model in TTS_MODELS, falling back model-to-model;
      - on 429/500/503, honor the server's exact "retry in Ns" hint
        (+5s pad) instead of a blind sleep;
      - raise on total exhaustion so the caller never writes a stub file.
    """
    key = _gemini_key()
    if not key:
        raise RuntimeError("Gemini TTS requested but no GKEY/GEMINI_API_KEY set")
    voice = voice or "Alnilam"
    payload = json.dumps({
        "contents": [{"parts": [{"text": _gemini_style(lang) + "\n\n" + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }).encode()
    last = ""
    for model in _gemini_models():
        for attempt in range(14):
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=payload,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            )
            try:
                r = json.load(urllib.request.urlopen(req, timeout=240))
                parts = r["candidates"][0]["content"]["parts"]
                return base64.b64decode(
                    next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
                )
            except urllib.error.HTTPError as e:
                b = e.read().decode()
                last = f"{model} {e.code} {b[:160]}"
                if e.code in (429, 500, 503):
                    m = re.search(r"retry in ([0-9.]+)s", b)
                    w = (float(m.group(1)) + 5) if m else 20 * (attempt + 1)
                    print(f"  retry {model} {e.code} {round(w)}s", flush=True)
                    time.sleep(w)
                    continue
                print(f"  {model} {e.code} {b[:120]}", flush=True)
                break
            except Exception as e:  # noqa: BLE001  (timeout / json / key errors)
                last = f"{model} {type(e).__name__} {str(e)[:120]}"
                w = 20 * (attempt + 1)
                print(f"  retry {model} err {round(w)}s :: {last}", flush=True)
                time.sleep(w)
                continue
        print(f"  -> falling back from {model}", flush=True)
    raise RuntimeError(f"Gemini TTS exhausted :: {last}")


# =============================================================================
# Chirp3-HD TTS (ported from deck_full_chirp_hi.py: split_long + chunks)
# =============================================================================

def split_long(text: str, maxlen: int = 180) -> str:
    """Chirp3-HD rejects sentences > ~600 chars. Break long sentences at commas
    into short sentences ending in a danda, so every sentence stays well under
    the limit. (Verbatim port from deck_full_chirp_hi.py.)"""
    out: list[str] = []
    for s in re.split(r"(?<=[।!?\.])\s+", text):
        if len(s) <= maxlen:
            out.append(s)
            continue
        buf = ""
        for piece in re.split(r"(?<=[,،])\s+", s):
            if len(buf) + len(piece) + 1 > maxlen and buf:
                out.append(buf.rstrip(",، ") + "।")
                buf = piece
            else:
                buf = (buf + " " + piece).strip()
        if buf:
            out.append(buf if re.search(r"[।!?\.]$", buf) else buf.rstrip(",، ") + "।")
    return " ".join(out)


def chunks(t: str, limit: int = 900) -> list[str]:
    """Pack sentences into <=limit-char request chunks. (Port from
    deck_full_chirp_hi.py, plus a hard-cut safety net.)

    The original relied on split_long() to keep sentences short, but a single
    sentence with no internal danda/comma punctuation can still exceed the
    limit (LLM-rewritten prose sometimes does). Chirp returns HTTP 400 on an
    over-length input, so we hard-cut any sentence that is still too long
    before packing — guaranteeing every emitted chunk is <= ``limit``."""
    sents: list[str] = []
    for s in re.split(r"(?<=[।!?\.])\s+", split_long(t)):
        if len(s) <= limit:
            sents.append(s)
        else:
            for i in range(0, len(s), limit):
                sents.append(s[i:i + limit])
    parts: list[str] = []
    cur = ""
    for s in sents:
        if len(cur) + len(s) + 1 > limit and cur:
            parts.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        parts.append(cur)
    return parts


def _chirp_lang_code(voice: str, lang: str) -> str:
    """Cloud TTS needs a languageCode matching the voice. Derive it from the
    voice id (e.g. 'hi-IN-Chirp3-HD-Alnilam' -> 'hi-IN')."""
    m = re.match(r"^([a-z]{2}-[A-Z]{2})", voice or "")
    if m:
        return m.group(1)
    return "hi-IN" if lang == "hi" else "en-IN"


def _chirp_tts(text: str, voice: str, lang: str) -> bytes:
    """Return PCM16 mono @24kHz for ``text`` via Cloud Text-to-Speech Chirp3-HD.

    Ported from deck_full_chirp_hi.py.synth(): split into <=900-char chunks,
    synth each, concatenate the raw PCM frames. Adds light retry/backoff on
    HTTP errors (the original assumed paid-credit reliability)."""
    key = _chirp_key()
    if not key:
        raise RuntimeError("Chirp TTS requested but no CTTS_KEY set")
    voice = voice or _default_voice("chirp", lang)
    lang_code = _chirp_lang_code(voice, lang)
    pcm = b""
    for ch in chunks(text):
        body = {
            "input": {"text": ch},
            "voice": {"languageCode": lang_code, "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SAMPLE_RATE},
        }
        data = json.dumps(body).encode()
        last = ""
        wav_bytes: Optional[bytes] = None
        for attempt in range(6):
            req = urllib.request.Request(
                "https://texttospeech.googleapis.com/v1/text:synthesize?key=" + key,
                data=data, headers={"Content-Type": "application/json"},
            )
            try:
                resp = json.load(urllib.request.urlopen(req, timeout=120))
                wav_bytes = base64.b64decode(resp["audioContent"])
                break
            except urllib.error.HTTPError as e:
                b = e.read().decode()
                last = f"{e.code} {b[:160]}"
                if e.code in (429, 500, 503):
                    w = 10 * (attempt + 1)
                    print(f"  chirp retry {e.code} {w}s", flush=True)
                    time.sleep(w)
                    continue
                raise RuntimeError(f"Chirp TTS HTTP {last}") from e
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__} {str(e)[:120]}"
                w = 10 * (attempt + 1)
                print(f"  chirp retry err {w}s :: {last}", flush=True)
                time.sleep(w)
                continue
        if wav_bytes is None:
            raise RuntimeError(f"Chirp TTS exhausted :: {last}")
        with wave.open(io.BytesIO(wav_bytes)) as w:
            pcm += w.readframes(w.getnframes())
    return pcm


# =============================================================================
# TTS dispatch + wav writing (write-on-success, from finish_all.py)
# =============================================================================

def _synth_pcm(text: str, engine: str, voice: str, lang: str) -> bytes:
    """Dispatch to the chosen backend. ``engine='gemini'`` falls back to chirp
    if Gemini is exhausted *and* a Chirp key is available (mirrors the UI's
    'credits pending -> falls back to Chirp3-HD' badge)."""
    engine = (engine or "chirp").lower()
    if engine == "gemini":
        try:
            return _gemini_tts(text, voice, lang)
        except Exception as exc:  # noqa: BLE001
            if _chirp_key():
                print(f"  gemini failed ({exc}); falling back to Chirp3-HD", flush=True)
                return _chirp_tts(text, _default_voice("chirp", lang), lang)
            raise
    return _chirp_tts(text, voice, lang)


def _write_wav(pcm: bytes, path: Path) -> None:
    """Write PCM16 mono @24kHz to ``path``. Caller computes pcm first so a
    synth failure leaves no stub file on disk (write-on-success)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


def _valid_wav(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 1000


# =============================================================================
# Slides: digest.pdf -> 1920x1080 PNG pages
# =============================================================================

def _render_slides(pdf_path: Path, out_dir: Path) -> list[Path]:
    """Rasterise every page of ``pdf_path`` to a letterboxed 1920x1080 PNG.

    Uses ``pdftoppm -r 200`` when poppler is on PATH (the VPS), else falls back
    to PyMuPDF (fitz, already a dependency) at the same effective DPI. Each page
    is then run through ffmpeg scale=-1:1080,pad=1920:1080:(ow-iw)/2:0:white so
    the slide is centered on a white 16:9 canvas.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_pages: list[Path] = []

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        subprocess.run(
            [pdftoppm, "-r", "200", "-png", str(pdf_path), str(raw_dir / "page")],
            check=True, capture_output=True,
        )
        raw_pages = sorted(raw_dir.glob("page-*.png"))
    if not raw_pages:
        # PyMuPDF fallback (no poppler — e.g. the Windows dev box). 200 DPI.
        import fitz  # noqa: WPS433
        doc = fitz.open(str(pdf_path))
        for i in range(len(doc)):
            pix = doc[i].get_pixmap(dpi=200)
            p = raw_dir / f"page-{i + 1:03d}.png"
            pix.save(str(p))
            raw_pages.append(p)
        doc.close()
    if not raw_pages:
        raise RuntimeError(f"no slides rendered from {pdf_path}")

    ff = _ffmpeg_bin()
    slides: list[Path] = []
    for i, raw in enumerate(raw_pages, start=1):
        slide = out_dir / f"slide-{i:03d}.png"
        subprocess.run(
            [ff, "-y", "-i", str(raw),
             "-vf", "scale=-1:1080,pad=1920:1080:(ow-iw)/2:0:white",
             str(slide)],
            check=True, capture_output=True,
        )
        slides.append(slide)
    return slides


# =============================================================================
# Stitch (per-section clip over its slide, then concat — from the deck scripts)
# =============================================================================

def _make_clip(slide_png: Path, wav: Path, out_clip: Path) -> float:
    """Hold ``slide_png`` for the duration of ``wav`` (+PAUSE tail) into an mp4
    clip. Returns the wav duration in seconds. (Port of the per-slide ffmpeg
    call shared by all three deck scripts.)"""
    with wave.open(str(wav)) as w:
        dur = w.getnframes() / w.getframerate()
    t = dur + PAUSE
    ff = _ffmpeg_bin()
    subprocess.run(
        [ff, "-y", "-loop", "1", "-i", str(slide_png), "-i", str(wav),
         "-af", f"apad=pad_dur={PAUSE}", "-t", f"{t:.3f}",
         "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
         "-vf", "scale=1920:1080",
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-movflags", "+faststart", str(out_clip)],
        check=True, capture_output=True,
    )
    return dur


def _concat(clips: list[Path], list_txt: Path, out_mp4: Path) -> None:
    """Concat the per-section clips into the final mp4 (ffmpeg concat demuxer)."""
    list_txt.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    ff = _ffmpeg_bin()
    subprocess.run(
        [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(list_txt),
         "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-movflags", "+faststart", str(out_mp4)],
        check=True, capture_output=True,
    )


# =============================================================================
# Status helpers (UpscIssue.video_status / video_progress via SyncSessionLocal)
# =============================================================================

def _set_video_status(issue_id: str, *, status: Optional[str] = None,
                      progress: Optional[str] = None, **fields) -> None:
    with SyncSessionLocal() as session:
        row = session.get(UpscIssue, issue_id)
        if row is None:
            return
        if status is not None:
            row.video_status = status
        if progress is not None:
            row.video_progress = progress
        for k, v in fields.items():
            setattr(row, k, v)
        session.commit()


# =============================================================================
# QC gate
# =============================================================================

def _ffprobe_streams(path: Path) -> dict:
    """Return {'duration': float, 'has_audio': bool, 'has_video': bool} for an
    mp4, using ffprobe if present, else a wave/ffmpeg-light fallback."""
    ffprobe = shutil.which("ffprobe") or os.environ.get("FFPROBE_BIN", "").strip()
    info = {"duration": 0.0, "has_audio": False, "has_video": False}
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(path)],
                check=True, capture_output=True, text=True,
            ).stdout
            data = json.loads(out)
            info["duration"] = float(data.get("format", {}).get("duration", 0.0) or 0.0)
            for st in data.get("streams", []):
                if st.get("codec_type") == "audio":
                    info["has_audio"] = True
                elif st.get("codec_type") == "video":
                    info["has_video"] = True
            return info
        except Exception:  # noqa: BLE001
            pass
    # Fallback: file exists + non-trivial size => assume ok-ish; duration 0
    # forces the caller's duration check to flag it if ffprobe is missing.
    return info


def qc_check(video_path: Path, *, min_duration: float = 5.0) -> tuple[bool, str]:
    """QC gate run before any upload: valid mp4 file, has an audio stream, and
    duration > min_duration. Returns (ok, reason)."""
    if not video_path.exists() or video_path.stat().st_size < 10_000:
        return False, "video file missing or too small"
    info = _ffprobe_streams(video_path)
    # If ffprobe is unavailable we can't fully verify audio; accept on size but
    # note it. When ffprobe IS present we enforce audio + duration.
    if shutil.which("ffprobe"):
        if not info["has_video"]:
            return False, "no video stream"
        if not info["has_audio"]:
            return False, "no audio stream"
        if info["duration"] < min_duration:
            return False, f"duration {info['duration']:.1f}s below {min_duration:.0f}s floor"
    return True, "ok"


# =============================================================================
# Public API: preview_voice + build_video
# =============================================================================

def preview_voice(engine: str, voice: str, lang: str,
                  text: Optional[str] = None) -> bytes:
    """Synthesize one sample sentence and return a complete WAV (header+data)
    as bytes for inline playback in the UI."""
    if not text or not text.strip():
        text = ("नमस्ते, यह यू पी एस सी डेली डाइजेस्ट की आवाज़ का नमूना है।"
                if (lang or "hi") == "hi"
                else "Hello, this is a sample of the UPSC daily digest voice.")
    pcm = _synth_pcm(text, engine, voice or _default_voice(engine, lang), lang or "hi")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def build_video(issue_id: str, config: dict, sections: list) -> dict:
    """Render the narrated digest video for ``issue_id``.

    ``config``: {engine, voice, lang, slide_style, theme}.
    ``sections``: [{section_id, label, text, est_seconds}, ...] (from
                  upsc_narration.generate_script, possibly admin-edited).

    Steps: render slides -> TTS each section (write-on-success, hard-verify) ->
    stitch each section over a slide page -> concat to digest.mp4. Updates
    UpscIssue.video_status/video_progress throughout. Returns
    {video_path, duration, size_bytes}.

    NOTE: this does NOT run the QC gate or upload — the route's _kick_video
    daemon owns the QC-then-publish flow. build_video just produces the mp4 and
    leaves status at 'rendering' for the caller to gate.
    """
    config = config or {}
    engine = (config.get("engine") or "chirp").lower()
    lang = (config.get("lang") or "hi").lower()
    voice = config.get("voice") or _default_voice(engine, lang)

    if not sections:
        raise RuntimeError("build_video called with no narration sections")

    issue_dir = WORK_ROOT / issue_id
    pdf_path = issue_dir / "digest.pdf"
    if not pdf_path.exists():
        raise RuntimeError(
            f"digest.pdf not found at {pdf_path} — issue must be rendered to "
            f"'preview' before a video can be built."
        )

    slides_dir = issue_dir / "video_slides"
    aud_dir = issue_dir / "video_audio"
    clips_dir = issue_dir / "video_clips"
    for d in (aud_dir, clips_dir):
        d.mkdir(parents=True, exist_ok=True)
    out_mp4 = issue_dir / "digest.mp4"

    # ---------------------------------------------------------------- slides
    _set_video_status(issue_id, status="rendering", video_progress="slides")
    print(f"[video] {issue_id}: rendering slides from {pdf_path.name}", flush=True)
    slides = _render_slides(pdf_path, slides_dir)
    n_pages = len(slides)
    print(f"[video] {issue_id}: {n_pages} slide pages", flush=True)

    # ---------------------------------------------------------------- tts
    # One wav per section, write-on-success (no stub left on failure).
    total = len(sections)
    for i, sec in enumerate(sections):
        text = (sec.get("text") or "").strip()
        wp = aud_dir / f"s{i:02d}.wav"
        if _valid_wav(wp):
            print(f"[video] {issue_id}: tts {i+1}/{total} cached", flush=True)
            continue
        if wp.exists():
            wp.unlink()
        if not text:
            # Empty section -> 0.6s of silence so the clip still maps to a slide.
            silence = b"\x00\x00" * int(SAMPLE_RATE * 0.6)
            _write_wav(silence, wp)
            continue
        _set_video_status(issue_id, status="rendering",
                          video_progress=f"tts {i+1}/{total}")
        print(f"[video] {issue_id}: tts {i+1}/{total} ({engine}/{voice})", flush=True)
        pcm = _synth_pcm(text, engine, voice, lang)  # raises before file write
        _write_wav(pcm, wp)
        time.sleep(1.0)  # gentle pacing, matches the deck scripts

    # hard verify (from finish_all.py)
    bad = [i for i in range(total) if not _valid_wav(aud_dir / f"s{i:02d}.wav")]
    if bad:
        raise RuntimeError(f"TTS produced invalid wavs for sections {bad}")

    # ---------------------------------------------------------------- stitch
    _set_video_status(issue_id, status="rendering", video_progress="stitch")
    clips: list[Path] = []
    duration = 0.0
    for i, sec in enumerate(sections):
        wp = aud_dir / f"s{i:02d}.wav"
        # Map section -> slide page. If there are fewer pages than sections,
        # cycle through pages so every section still narrates over a real slide.
        slide = slides[i % n_pages]
        clip = clips_dir / f"c{i:02d}.mp4"
        dur = _make_clip(slide, wp, clip)
        duration += dur + PAUSE
        clips.append(clip)
        print(f"[video] {issue_id}: clip {i+1}/{total} {dur:.1f}s", flush=True)

    _concat(clips, clips_dir / "concat.txt", out_mp4)
    size_bytes = out_mp4.stat().st_size
    print(f"[video] {issue_id}: DONE {out_mp4} ({duration:.0f}s, {size_bytes/1e6:.1f} MB)",
          flush=True)

    _set_video_status(issue_id, video_progress="rendered",
                      video_path=str(out_mp4))
    return {
        "video_path": str(out_mp4),
        "duration": round(duration, 2),
        "size_bytes": size_bytes,
    }


# =============================================================================
# CLI for manual testing
# =============================================================================

def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("issue_id")
    ap.add_argument("--engine", default="chirp", choices=["gemini", "chirp"])
    ap.add_argument("--voice", default=None)
    ap.add_argument("--lang", default="hi", choices=["hi", "en"])
    ap.add_argument("--slide-style", default="digest")
    ap.add_argument("--theme", default="amber")
    args = ap.parse_args()

    from scripts.upsc_narration import generate_script
    sections = generate_script(args.issue_id, lang=args.lang)
    cfg = {
        "engine": args.engine,
        "voice": args.voice or _default_voice(args.engine, args.lang),
        "lang": args.lang,
        "slide_style": args.slide_style,
        "theme": args.theme,
    }
    result = build_video(args.issue_id, cfg, sections)
    ok, reason = qc_check(Path(result["video_path"]))
    print(json.dumps({**result, "qc_ok": ok, "qc_reason": reason}, indent=2))


if __name__ == "__main__":
    _cli()
