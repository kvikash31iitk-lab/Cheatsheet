"""Self-hosted Whisper via ``faster-whisper``.

Used when ``WHISPER_BACKEND=local`` is set in the environment. The model is
loaded once per process and reused across requests; first call blocks for
~5-10 seconds while CTranslate2 maps the model into RAM.

Returns a dict that mirrors the Groq Whisper API response shape so the
caller in ``transcribe_with_frames.py`` doesn't have to know which backend
ran:

    {
        "text": "<full transcript>",
        "segments": [
            {"start": 0.0, "end": 4.32, "text": "..."},
            ...
        ],
    }

Memory footprint depends on model size:
    tiny    ≈ 0.5 GB    (poor accuracy, ~30s for 30-min audio on 1 vCPU)
    base    ≈ 0.7 GB    (OK)
    small   ≈ 1.2 GB    (recommended sweet spot, ~3-5 min for 30-min audio)
    medium  ≈ 2.5 GB    (good, slower)
    large-v3≈ 4.0 GB    (best, tight on a 4 GB VPS)

Override the model with ``WHISPER_MODEL`` env var (default: ``small``).
"""
from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any

_model = None
_model_lock = Lock()


def _get_model():
    """Lazily construct the WhisperModel. Threadsafe singleton."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel  # imported lazily

            model_size = os.environ.get("WHISPER_MODEL", "small")
            compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
            device = os.environ.get("WHISPER_DEVICE", "cpu")
            print(
                f"[whisper_local] loading {model_size} on {device} ({compute_type})...",
                flush=True,
            )
            _model = WhisperModel(model_size, device=device, compute_type=compute_type)
            print("[whisper_local] model ready.", flush=True)
    return _model


def transcribe_chunk(audio_path: str | Path) -> dict[str, Any]:
    """Transcribe one audio chunk to the Groq-shaped response dict."""
    model = _get_model()
    # Greedy decoding (beam_size=1) keeps CPU latency in check at the cost
    # of a tiny accuracy hit — fine for educational content.
    segments_iter, _info = model.transcribe(
        str(audio_path),
        language=os.environ.get("WHISPER_LANGUAGE") or None,  # auto-detect when unset
        beam_size=1,
        vad_filter=True,
    )
    segments = []
    text_parts = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        segments.append(
            {
                "start": float(seg.start or 0.0),
                "end": float(seg.end or 0.0),
                "text": text,
            }
        )
        text_parts.append(text)
    return {"text": " ".join(text_parts), "segments": segments}


def warmup() -> None:
    """Load the model now so the first user request doesn't pay the cost.
    Called from deploy scripts after ``pip install``."""
    _get_model()


if __name__ == "__main__":
    # CLI: `python -m scripts.whisper_local <audio_path>` for quick checks.
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m scripts.whisper_local <audio_file>", file=sys.stderr)
        sys.exit(1)
    out = transcribe_chunk(sys.argv[1])
    print(json.dumps(out, ensure_ascii=False, indent=2))
