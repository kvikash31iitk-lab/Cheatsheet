"""Single-worker async queue + the orchestration that runs one job end-to-end.

Job lifecycle:
  1. /cheat <url> or /book <url>  → enqueue Job(...)
  2. Worker dequeues sequentially.
  3. For each job:
       a. Send "Queued" message + create ProgressEditor on it.
       b. Resolve video metadata, check cache.
       c. If transcript missing → run_pipeline (frame extraction iff book).
       d. Author markdown via Groq Llama (cheatsheet or book).
       e. Render PDF via build_cheatsheet or build_illustrated_book.
       f. Upload PDF as a Telegram document; replace progress with "Done in Xs".
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from telegram import Bot
from telegram.constants import ParseMode

from . import cache, media_uploads
from .config import SCRIPTS_DIR, TELEGRAM_UPLOAD_MAX_MB, WORK_ROOT
from .progress import ProgressEditor

# Make the existing scripts importable.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@dataclass(frozen=True)
class TelegramMedia:
    """Telegram identifiers and safe metadata; never rendered in status."""

    file_id: str
    file_unique_id: str
    file_name: str
    file_size: int | None
    is_video: bool
    title: str


@dataclass
class Job:
    chat_id: int
    user_id: int
    user_name: str
    url: str
    fmt: str  # "cheat" or "book"
    refresh: bool = False
    # Opt-in PDF enhancements selected before submission. Each entry is a
    # short flag from ``cache.FEATURE_ORDER`` (e.g. "summary", "tldr",
    # "qna", "mermaid", "chapters"). Empty list = legacy PDF (no extras).
    # Drives both the author prompt and the PDF builder's behaviour, and is
    # hashed into the cache key so different selections don't collide.
    features: list[str] = field(default_factory=list)
    source_kind: str = "youtube"
    telegram_media: TelegramMedia | None = None
    enqueued_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.source_kind == "telegram":
            if self.telegram_media is None:
                raise ValueError("Telegram jobs require media metadata")
        elif self.source_kind == "youtube":
            if not self.url:
                raise ValueError("YouTube jobs require a URL")
        else:
            raise ValueError("Unknown job source")


class Queue:
    def __init__(self):
        self._q: asyncio.Queue[Job] = asyncio.Queue()
        self._snapshot: list[Job] = []
        self._current: Job | None = None
        self._lock = asyncio.Lock()

    async def put(self, job: Job) -> int:
        """Enqueue and return the position (1 = next up)."""
        async with self._lock:
            self._snapshot.append(job)
            position = len(self._snapshot)
        await self._q.put(job)
        return position

    async def get(self) -> Job:
        job = await self._q.get()
        async with self._lock:
            if self._snapshot and self._snapshot[0] is job:
                self._snapshot.pop(0)
            self._current = job
        return job

    async def done(self) -> None:
        async with self._lock:
            self._current = None
        self._q.task_done()

    def status(self) -> dict:
        return {
            "current": self._current,
            "queued": list(self._snapshot),
        }


queue = Queue()


# === orchestration ==========================================================

async def run_job(bot: Bot, job: Job) -> None:
    """Process a single job end-to-end. Catches and reports errors."""
    # 1. Initial message
    msg = await bot.send_message(job.chat_id, "Queued, starting...")
    editor = ProgressEditor(bot, job.chat_id, msg.message_id)

    started_at = time.time()
    try:
        is_upload = job.source_kind == "telegram"
        if is_upload:
            await editor.update("Preparing uploaded media...", force=True)
            media = job.telegram_media
            if media is None:
                await editor.update("Please upload the file again.", force=True)
                return
            video_id = media_uploads.upload_cache_id(
                job.chat_id, media.file_unique_id, job.url
            )
        else:
            await editor.update("Resolving video...", force=True)
            # 2. Pull video ID
            from transcribe_with_frames import extract_video_id
            try:
                video_id = extract_video_id(job.url)
            except ValueError:
                await editor.update("Could not parse YouTube URL.", force=True)
                return

        if job.refresh:
            cache.invalidate(video_id)

        # Normalise once so cache hashing + author/builder all see the same
        # canonical list (and missing/unknown flags don't accidentally fork
        # the cache key).
        features = cache.normalize_features(job.features)

        # 3. Cache hit shortcut — feature-keyed so a previous run with a
        # different toggle set doesn't accidentally serve the wrong PDF.
        cached_pdf = (cache.cheatsheet_pdf_path(video_id, features)
                      if job.fmt == "cheat"
                      else cache.book_pdf_path(video_id, features))
        if cached_pdf.exists():
            await editor.update("Cached PDF found, sending...", force=True)
            await bot.send_document(job.chat_id, document=open(cached_pdf, "rb"),
                                    filename=cached_pdf.name)
            await editor.update(
                f"Done (from cache, took {int(time.time()-started_at)}s).",
                force=True)
            return

        # 4. Run transcription pipeline if needed
        need_transcript = not cache.has_transcript(video_id)
        need_frames = (job.fmt == "book" and not cache.has_frames(video_id))
        if need_transcript or need_frames:
            def cb(msg_text: str):
                editor.update_threadsafe(msg_text)

            if is_upload:
                from transcribe_with_frames import run_local_media_pipeline

                staging_dir = None
                try:
                    media = job.telegram_media
                    if media is None:
                        await editor.update(
                            "Please upload the file again.", force=True
                        )
                        return
                    staging_dir = media_uploads.create_staging_dir(video_id)
                    source_path = staging_dir / (
                        "source" + media_uploads.safe_media_suffix(media.file_name)
                    )
                    await editor.update(
                        "Downloading uploaded media...", force=True
                    )
                    await media_uploads.download_media(
                        bot,
                        file_id=media.file_id,
                        declared_size=media.file_size,
                        destination=source_path,
                    )
                    pipeline_result = await asyncio.to_thread(
                        run_local_media_pipeline,
                        source_path,
                        staging_dir / "pipeline",
                        video_id=video_id,
                        title=media.title,
                        transcribe=need_transcript,
                        extract_frames=need_frames,
                        on_progress=cb,
                    )
                    cache.adopt_pipeline_outputs(video_id, pipeline_result)
                except media_uploads.MediaUploadError as exc:
                    await editor.update(str(exc), force=True)
                    return
                except (RuntimeError, ValueError):
                    traceback.print_exc()
                    await editor.update(
                        "Uploaded-media processing failed. Make sure the file "
                        "contains playable audio, or try again later.",
                        force=True,
                    )
                    return
                finally:
                    media_uploads.remove_staging_dir(staging_dir)
            else:
                from transcribe_with_frames import run_pipeline
                from scripts.ytdlp_client import YtDlpError

                work_dir = WORK_ROOT / video_id
                try:
                    pipeline_result = await asyncio.to_thread(
                        run_pipeline,
                        job.url,
                        work_dir,
                        extract_frames=(job.fmt == "book"),
                        on_progress=cb,
                    )
                except YtDlpError as exc:
                    media_kind = "video" if job.fmt == "book" else "audio or video"
                    await editor.update(
                        f"{exc.public_message}\n\n"
                        f"Fallback: send the actual {media_kind} file here "
                        f"(under {TELEGRAM_UPLOAD_MAX_MB} MB), then choose "
                        "the format and extras. That path does not contact YouTube.",
                        force=True,
                    )
                    return
                except RuntimeError:
                    traceback.print_exc()
                    await editor.update(
                        "Video processing failed before transcription. "
                        "Please try again later.",
                        force=True,
                    )
                    return
                cache.adopt_pipeline_outputs(video_id, pipeline_result)

        meta = cache.load_meta(video_id)
        title_hint = meta.title if meta else None
        duration_s = meta.duration_seconds if meta else None

        # 5. Author markdown
        slot = cache.slot(video_id)

        def author_cb(msg_text: str):
            editor.update_threadsafe(msg_text)

        if job.fmt == "cheat":
            await editor.update("Condensing transcript...", force=True)
            from .author import author_cheatsheet
            md = await asyncio.to_thread(
                author_cheatsheet,
                cache.transcript_path(video_id),
                title_hint=title_hint,
                duration_seconds=duration_s,
                on_progress=author_cb,
                features=features,
            )
            md_path = cache.cheatsheet_md_path(video_id, features)
            md_path.write_text(md, encoding="utf-8")
            cache.update_meta(video_id, cheatsheet_at=time.time())

            # 6. Render PDF
            await editor.update("Rendering PDF...", force=True)
            from build_cheatsheet import build as build_cheat
            pdf_path = cache.cheatsheet_pdf_path(video_id, features)
            await asyncio.to_thread(
                build_cheat,
                src=md_path, out=pdf_path,
                title=(title_hint or "Cheatsheet"),
                features=features,
                source_url=job.url,
            )
        else:  # book
            await editor.update("Condensing transcript...", force=True)
            from .author import author_book
            md = await asyncio.to_thread(
                author_book,
                cache.transcript_path(video_id),
                cache.frames_index_path(video_id),
                title_hint=title_hint,
                duration_seconds=duration_s,
                on_progress=author_cb,
                features=features,
            )
            md_path = cache.book_md_path(video_id, features)
            md_path.write_text(md, encoding="utf-8")
            cache.update_meta(video_id, book_at=time.time())

            # 6. Render PDF
            await editor.update("Rendering PDF...", force=True)
            from build_illustrated_book import build as build_book
            pdf_path = cache.book_pdf_path(video_id, features)
            await asyncio.to_thread(
                build_book,
                src=md_path, out=pdf_path,
                title=(title_hint or "Notes"),
                image_base=cache.slot(video_id),
                features=features,
                source_url=job.url,
            )

        # 7. Send the PDF
        await editor.update("Sending PDF...", force=True)
        with open(pdf_path, "rb") as f:
            await bot.send_document(job.chat_id, document=f,
                                    filename=pdf_path.name)
        elapsed = int(time.time() - started_at)
        await editor.update(
            f"Done in {elapsed//60}m {elapsed%60}s.", force=True)

    except Exception:
        traceback.print_exc()
        try:
            await editor.update(
                "Generation failed unexpectedly. Please try again later.",
                force=True,
            )
        except Exception:
            pass


async def worker_loop(bot: Bot) -> None:
    print("[worker] started, waiting for jobs")
    while True:
        job = await queue.get()
        try:
            await run_job(bot, job)
        finally:
            await queue.done()
