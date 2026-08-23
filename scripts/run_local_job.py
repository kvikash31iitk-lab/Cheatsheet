#!/usr/bin/env python3
"""Run an end-to-end local generation flow from a YouTube URL to PDF.

This utility is useful when you want to bypass Telegram and execute:

1. URL validation + metadata fetch
2. Transcript + optional frame extraction
3. Authoring (cheatsheet / book markdown)
4. PDF rendering

The output is written to disk as markdown + PDF artifacts and can be used to
debug the full path independently from the web bot/API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Make project-level imports work whether run as script or module.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.youtube_urls import validate_public_youtube_url
from bot import cache as bot_cache
from bot import config as bot_config
from bot.author import author_book, author_cheatsheet
from scripts.build_cheatsheet import build as build_cheatsheet
from scripts.build_illustrated_book import build as build_book
from scripts.transcribe_with_frames import extract_video_id, run_pipeline
from scripts.ytdlp_client import YtDlpError


DEFAULT_RUN_ROOT = PROJECT_ROOT / "data" / "local-runs"
MIN_MARKDOWN_CHARS = 240
MIN_PDF_TEXT_CHARS = 180
MIN_PDF_BYTES = 1_024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_job_manifest(path: Path, *, url: str, video_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if not isinstance(payload.get("stages"), dict):
                payload["stages"] = {}
            payload["attempts"] = int(payload.get("attempts") or 0) + 1
            payload["updated_at"] = _utc_now()
            return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    now = _utc_now()
    return {
        "schema_version": 1,
        "url": url,
        "video_id": video_id,
        "status": "running",
        "attempts": 1,
        "created_at": now,
        "updated_at": now,
        "stages": {},
    }


def _record_stage(
    path: Path,
    manifest: dict[str, Any],
    name: str,
    status: str,
    **details: Any,
) -> None:
    stage = manifest.setdefault("stages", {}).setdefault(name, {})
    stage["status"] = status
    if status == "running":
        stage["started_at"] = _utc_now()
        stage["attempts"] = int(stage.get("attempts") or 0) + 1
        stage.pop("error", None)
    else:
        stage["finished_at"] = _utc_now()
    stage.update({key: value for key, value in details.items() if value is not None})
    manifest["updated_at"] = _utc_now()
    manifest["status"] = "failed" if status == "failed" else "running"
    _atomic_write_json(path, manifest)


def validate_markdown_artifact(path: Path) -> dict[str, Any]:
    """Reject suspiciously small or leaked-reasoning author output."""

    if not path.is_file():
        raise RuntimeError("Markdown artifact is missing")
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) < MIN_MARKDOWN_CHARS:
        raise RuntimeError(
            f"Markdown artifact is too small ({len(text)} characters)"
        )
    if "<think>" in text.casefold() or "</think>" in text.casefold():
        raise RuntimeError("Markdown artifact contains model reasoning tags")
    if not any(line.lstrip().startswith("#") for line in text.splitlines()):
        raise RuntimeError("Markdown artifact has no document heading")
    return {"characters": len(text), "words": len(text.split())}


def validate_pdf_artifact(path: Path) -> dict[str, Any]:
    """Open and text-check the rendered PDF before it becomes final."""

    if not path.is_file() or path.stat().st_size < MIN_PDF_BYTES:
        raise RuntimeError("Rendered PDF is missing or unexpectedly small")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = len(reader.pages)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise RuntimeError(f"Rendered PDF cannot be opened: {exc}") from exc
    if pages < 1:
        raise RuntimeError("Rendered PDF contains no pages")
    if len(text.strip()) < MIN_PDF_TEXT_CHARS:
        raise RuntimeError(
            f"Rendered PDF contains too little readable text ({len(text.strip())} characters)"
        )
    if "<think>" in text.casefold() or "</think>" in text.casefold():
        raise RuntimeError("Rendered PDF contains model reasoning tags")
    return {
        "pages": pages,
        "text_characters": len(text.strip()),
        "size_bytes": path.stat().st_size,
    }


def _normalize_features(raw: str | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        requested = [token.strip().lower() for token in raw.split(",") if token.strip()]
    else:
        requested = list(raw)
    return bot_cache.normalize_features(requested)


def _progress(message: str) -> None:
    print(f"[local-job] {message}", flush=True)


def _safe_int(value: float | None) -> int:
    try:
        return int(round(float(value or 0.0), 0))
    except (TypeError, ValueError):
        return 0


def _fallback_text(message: str) -> str:
    return (
        f"{message}\n\n"
        f"If this keeps failing due YouTube route blocking, try one of:\n"
        f"- run a local media-only path using `run_local_media_pipeline`, or\n"
        f"- switch this environment to a healthy proxy / VPN route."
    )


def _load_cached_pipeline_result(
    video_id: str,
    *,
    need_frames: bool,
) -> dict[str, Any]:
    """Load transcript/frame artifacts from the shared bot cache, if present."""
    transcript_txt = bot_cache.transcript_path(video_id)
    transcript_json = bot_cache.slot(video_id) / "transcript.json"
    frames_index = bot_cache.frames_index_path(video_id)
    frames_dir = bot_cache.frames_dir_path(video_id)
    if not transcript_txt.exists():
        raise FileNotFoundError("cached transcript not found")
    if need_frames and not frames_index.exists():
        raise FileNotFoundError("cached frames index not found")

    meta = bot_cache.load_meta(video_id)
    return {
        "video_id": video_id,
        "title": meta.title if meta else "",
        "duration_seconds": float(meta.duration_seconds) if meta else 0.0,
        "transcript_txt": transcript_txt,
        "transcript_json": transcript_json if transcript_json.exists() else None,
        "transcript_with_frames": (
            bot_cache.slot(video_id) / "transcript_with_frames.txt"
        )
        if (bot_cache.slot(video_id) / "transcript_with_frames.txt").exists()
        else None,
        "frames_dir": frames_dir if frames_dir.exists() else None,
        "frames_index": frames_index if frames_index.exists() else None,
    }


def run_url_job(
    url: str,
    *,
    kind: str = "cheatsheet",
    work_root: Path | None = None,
    output_pdf: Path | None = None,
    output_md: Path | None = None,
    features: list[str] | None = None,
    use_cached_pipeline: bool = True,
    progress: bool = True,
    on_progress: Callable[[str], None] | None = None,
    on_ingest: Callable[[dict[str, Any]], None] | None = None,
    cost_sink: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Run full local URL pipeline and return artifact metadata.

    Returns a dict with final paths + source metadata. Raises on hard failure.
    """
    emit = on_progress or (
        _progress if progress else (lambda *_args, **_kwargs: None)
    )
    if kind not in {"cheatsheet", "book"}:
        raise ValueError("kind must be 'cheatsheet' or 'book'")

    video_id = extract_video_id(url)
    root = Path(work_root) if work_root else DEFAULT_RUN_ROOT
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / video_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "job.manifest.json"
    manifest = _load_job_manifest(manifest_path, url=url, video_id=video_id)
    _atomic_write_json(manifest_path, manifest)
    current_stage = "validate_url"

    try:
        _record_stage(manifest_path, manifest, current_stage, "running")
        validated = validate_public_youtube_url(url)
        if isinstance(validated, str) and validated:
            url = validated
        _record_stage(manifest_path, manifest, current_stage, "complete")
        emit(f"URL validated: {url}")

        extract_frames = kind == "book"
        feats = bot_cache.normalize_features(features or [])
        emit(f"Features: {', '.join(feats) or 'none'}")

        use_cache = bool(use_cached_pipeline)
        work_dir = run_dir
        emit(f"Work directory: {work_dir}")
        current_stage = "ingest"
        _record_stage(manifest_path, manifest, current_stage, "running")

        pipeline_result: dict[str, Any]
        if use_cache:
            try:
                emit("Checking cached pipeline outputs...")
                pipeline_result = _load_cached_pipeline_result(
                    video_id, need_frames=extract_frames
                )
                # Keep author/render artifacts with the shared transcript cache.
                work_dir = bot_cache.slot(video_id)
                emit("Using cached transcript/frame artifacts.")
                _record_stage(
                    manifest_path,
                    manifest,
                    current_stage,
                    "complete",
                    provider="shared_cache",
                )
            except FileNotFoundError:
                use_cache = False

        if not use_cache:
            emit("Running caption-first YouTube ingestion...")
            pipeline_result = run_pipeline(
                url,
                work_dir,
                extract_frames=extract_frames,
                on_progress=emit,
            )
            _record_stage(
                manifest_path,
                manifest,
                current_stage,
                "complete",
                provider=pipeline_result.get("transcript_provider") or "whisper",
                segments=pipeline_result.get("segments_count"),
            )

        title = pipeline_result.get("title") or None
        duration_seconds = pipeline_result.get("duration_seconds")
        transcript_txt = Path(pipeline_result["transcript_txt"])
        frames_index = pipeline_result.get("frames_index")
        frames_dir = pipeline_result.get("frames_dir")
        if not transcript_txt.exists() or transcript_txt.stat().st_size <= 40:
            raise RuntimeError("Transcript file missing or empty after ingestion stage.")

        # Web callers use this hook to persist source metadata and reserve
        # quota/wallet credit after captions are available but before the
        # comparatively expensive authoring step begins. Keeping the hook at
        # this boundary also avoids a separate yt-dlp metadata preflight,
        # which is often the least reliable request from a datacenter IP.
        if on_ingest is not None:
            on_ingest(
                {
                    "video_id": video_id,
                    "title": title or "",
                    "duration_seconds": float(duration_seconds or 0.0),
                    "transcript_provider": pipeline_result.get(
                        "transcript_provider"
                    )
                    or ("shared_cache" if use_cache else "whisper"),
                }
            )

        # Keep source URL and feature flags in final filenames for traceability.
        stamp = video_id
        feature_tag = bot_cache.features_suffix(feats)
        out_stem = f"{kind}{feature_tag}" if feature_tag else kind
        if output_md is None:
            output_md = (
                work_dir / f"{out_stem}.{stamp}.md"
                if use_cache
                else work_dir / f"{out_stem}.md"
            )
        if output_pdf is None:
            output_pdf = (
                work_dir / f"{out_stem}.{stamp}.pdf"
                if use_cache
                else work_dir / f"{out_stem}.pdf"
            )
        output_md = Path(output_md)
        output_pdf = Path(output_pdf)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)

        current_stage = "author"
        author_signature = _stable_signature(
            {
                "video_id": video_id,
                "kind": kind,
                "features": feats,
                "title": title or "",
                "duration_seconds": round(float(duration_seconds or 0.0), 2),
                "transcript_sha256": _file_sha256(transcript_txt),
                "frames_sha256": (
                    _file_sha256(Path(frames_index))
                    if frames_index and Path(frames_index).is_file()
                    else None
                ),
                "authoring_provider": bot_config.AUTHORING_PROVIDER,
                "authoring_model": bot_config.AUTHORING_MODEL,
            }
        )
        prior_author = manifest.get("stages", {}).get("author", {})
        if not isinstance(prior_author, dict):
            prior_author = {}
        author_artifact_matches = bool(
            prior_author.get("status") == "complete"
            and prior_author.get("author_signature") == author_signature
            and prior_author.get("markdown_path") == str(output_md.resolve())
            and output_md.is_file()
            and prior_author.get("markdown_sha256") == _file_sha256(output_md)
        )
        try:
            if not author_artifact_matches:
                raise RuntimeError("Authored artifact does not match this job input")
            markdown_quality = validate_markdown_artifact(output_md)
            markdown_sha256 = _file_sha256(output_md)
            emit(f"Reusing validated markdown: {output_md}")
            _record_stage(
                manifest_path, manifest, current_stage, "complete",
                reused=True,
                author_signature=author_signature,
                markdown_sha256=markdown_sha256,
                markdown_path=str(output_md.resolve()),
                **markdown_quality,
            )
        except RuntimeError:
            _record_stage(manifest_path, manifest, current_stage, "running")
            emit(f"Authoring {kind} notes...")
            if kind == "cheatsheet":
                author_kwargs: dict[str, Any] = {
                    "title_hint": title,
                    "duration_seconds": duration_seconds,
                    "on_progress": emit,
                    "features": feats,
                }
                if cost_sink is not None:
                    author_kwargs["cost_sink"] = cost_sink
                markdown = author_cheatsheet(transcript_txt, **author_kwargs)
            else:
                if frames_index is None:
                    raise RuntimeError("Book mode requires extracted frames index")
                author_kwargs = {
                    "title_hint": title,
                    "duration_seconds": duration_seconds,
                    "on_progress": emit,
                    "features": feats,
                }
                if cost_sink is not None:
                    author_kwargs["cost_sink"] = cost_sink
                markdown = author_book(
                    transcript_txt,
                    Path(frames_index),
                    **author_kwargs,
                )
            output_md.write_text(markdown, encoding="utf-8")
            markdown_quality = validate_markdown_artifact(output_md)
            markdown_sha256 = _file_sha256(output_md)
            _record_stage(
                manifest_path, manifest, current_stage, "complete",
                reused=False,
                author_signature=author_signature,
                markdown_sha256=markdown_sha256,
                markdown_path=str(output_md.resolve()),
                **markdown_quality,
            )
            emit(f"Writing markdown: {output_md}")

        current_stage = "render"
        pdf_quality: dict[str, Any] | None = None
        render_signature = _stable_signature(
            {
                "video_id": video_id,
                "kind": kind,
                "features": feats,
                "title": title or "",
                "markdown_sha256": markdown_sha256,
            }
        )
        prior_render = manifest.get("stages", {}).get("render", {})
        if not isinstance(prior_render, dict):
            prior_render = {}
        artifact_matches = bool(
            prior_render.get("status") == "complete"
            and prior_render.get("render_signature") == render_signature
            and prior_render.get("pdf_path") == str(output_pdf.resolve())
        )
        if output_pdf.exists() and artifact_matches:
            try:
                pdf_quality = validate_pdf_artifact(output_pdf)
                emit(f"Reusing validated PDF: {output_pdf}")
                _record_stage(
                    manifest_path, manifest, current_stage, "complete",
                    reused=True,
                    render_signature=render_signature,
                    markdown_sha256=markdown_sha256,
                    pdf_path=str(output_pdf.resolve()),
                    **pdf_quality,
                )
            except RuntimeError:
                pdf_quality = None

        if pdf_quality is None:
            _record_stage(manifest_path, manifest, current_stage, "running")
            temporary_pdf = output_pdf.with_name(
                f".{output_pdf.stem}.{uuid.uuid4().hex}.tmp.pdf"
            )
            emit(f"Rendering PDF: {output_pdf}")
            try:
                if kind == "cheatsheet":
                    build_cheatsheet(
                        output_md,
                        temporary_pdf,
                        title or "Cheatsheet",
                        features=feats,
                        source_url=url,
                    )
                else:
                    build_book(
                        output_md,
                        temporary_pdf,
                        title or "Notes",
                        Path(frames_dir).parent if frames_dir else work_dir,
                        None,
                        features=feats,
                        source_url=url,
                    )
                pdf_quality = validate_pdf_artifact(temporary_pdf)
                temporary_pdf.replace(output_pdf)
            finally:
                temporary_pdf.unlink(missing_ok=True)
            _record_stage(
                manifest_path, manifest, current_stage, "complete",
                reused=False,
                render_signature=render_signature,
                markdown_sha256=markdown_sha256,
                pdf_path=str(output_pdf.resolve()),
                **pdf_quality,
            )

        current_stage = "quality_gate"
        _record_stage(manifest_path, manifest, current_stage, "running")
        markdown_quality = validate_markdown_artifact(output_md)
        pdf_quality = validate_pdf_artifact(output_pdf)
        _record_stage(
            manifest_path,
            manifest,
            current_stage,
            "complete",
            markdown=markdown_quality,
            pdf=pdf_quality,
        )

        # Automatically clean up temporary audio and video media files to keep VPS disk free
        try:
            for pattern in ("session_full.mp3", "raw_audio.m4a", "raw_video.mp4", "*.part"):
                for media_f in work_dir.glob(pattern):
                    try:
                        media_f.unlink(missing_ok=True)
                    except OSError:
                        pass
        except Exception:
            pass

        result = {

            "kind": kind,
            "video_id": video_id,
            "url": url,
            "title": title or "",
            "duration_seconds": duration_seconds,
            "transcript_provider": pipeline_result.get("transcript_provider")
            or ("shared_cache" if use_cache else "whisper"),
            "source_cache_dir": str(bot_cache.slot(video_id)),
            "work_dir": str(work_dir),
            "manifest_path": str(manifest_path),
            "markdown_path": str(output_md),
            "pdf_path": str(output_pdf),
            "transcript_path": str(transcript_txt),
            "features": feats,
            "pdf_size_bytes": output_pdf.stat().st_size,
            "pdf_pages": pdf_quality["pages"],
        }
        manifest["status"] = "complete"
        manifest["result"] = result
        manifest["updated_at"] = _utc_now()
        _atomic_write_json(manifest_path, manifest)
        emit(f"Done: {output_pdf}")
        return result
    except Exception as exc:
        _record_stage(
            manifest_path,
            manifest,
            current_stage,
            "failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def _parse_features(raw: str | None) -> list[str]:
    return _normalize_features(raw)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local YouTube URL → author → PDF end-to-end."
    )
    parser.add_argument("url", help="Public YouTube URL (https only)")
    parser.add_argument(
        "--kind",
        choices=("cheatsheet", "book"),
        default="cheatsheet",
        help="Output type",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help=(
            "Base directory for generated work files. Defaults to "
            "data/local-runs/<video_id>."
        ),
    )
    parser.add_argument(
        "--out-pdf",
        default=None,
        help="Explicit PDF output path (overrides default)",
    )
    parser.add_argument(
        "--out-md",
        default=None,
        help="Explicit markdown output path (overrides default)",
    )
    parser.add_argument(
        "--features",
        default="",
        help="Comma-separated feature toggles (summary,tldr,qna,mermaid,chapters)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run of transcript/frame pipeline even if cache exists.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Only print errors/success summary, hide stage progress.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print final artifact metadata as JSON only.",
    )
    return parser.parse_args()


def _maybe_print(exc: Exception) -> None:
    print(
        _fallback_text(f"Could not complete local run: {exc}"),
        file=sys.stderr,
        flush=True,
    )


def main() -> None:
    args = _parse_args()
    feats = _parse_features(args.features)
    try:
        out = run_url_job(
            args.url,
            kind=args.kind,
            work_root=Path(args.work_dir) if args.work_dir else None,
            output_pdf=Path(args.out_pdf) if args.out_pdf else None,
            output_md=Path(args.out_md) if args.out_md else None,
            features=feats,
            use_cached_pipeline=not args.force,
            progress=not args.no_progress,
        )
    except YtDlpError as exc:
        print(f"Could not reach YouTube through this download route: {exc.public_message}", file=sys.stderr)
        _maybe_print(exc)
        sys.exit(2)
    except KeyboardInterrupt:
        print("Stopped by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        _maybe_print(exc)
        sys.exit(1)

    if args.json:
        print(json.dumps(out, indent=2))
        return

    secs = out.get("duration_seconds")
    mins = _safe_int(secs / 60 if isinstance(secs, (int, float)) else None)
    print(f"Done in local flow. duration={mins} min | pdf={out['pdf_path']}")


if __name__ == "__main__":
    main()
