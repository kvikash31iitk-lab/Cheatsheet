"""Minimal FastAPI service that wraps the existing bot pipeline.

This is the Phase-0 web backend: it exposes three endpoints —

    POST /api/generate          start a job (returns {"id": ...})
    GET  /api/jobs/{id}         poll job status
    GET  /api/files/{id}/pdf    download the rendered PDF

The pipeline modules (``scripts/transcribe_with_frames.py``,
``bot/author.py``, ``scripts/build_*.py``) are imported and reused as-is.

For Phase 0 there is no auth, no DB, no queue — jobs live in an in-memory
dict and run as ``asyncio.to_thread`` background tasks. Good enough to
demo the end-to-end browser flow; the next phase swaps this out for
Postgres + a proper worker.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Make the existing bot modules importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Augment PATH so subprocess calls find yt-dlp / ffmpeg / deno even when the
# server is launched from a shell that doesn't have them. Pip's user-install
# Scripts dir on Windows is not on the default system PATH.
def _augment_path() -> None:
    extra: list[str] = []
    if sys.platform == "win32":
        # Per-user pip Scripts dir (where yt-dlp.exe lives).
        appdata_scripts = Path(os.environ.get("APPDATA", "")) / "Python"
        for sub in appdata_scripts.glob("Python*/Scripts"):
            extra.append(str(sub))
        # Common ffmpeg install locations.
        for cand in [
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        ]:
            if Path(cand).exists():
                extra.append(cand)
        # winget puts ffmpeg under Packages/Gyan.FFmpeg_*/ffmpeg-*/bin
        winget_pkgs = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"))
        for bin_dir in winget_pkgs.glob("Gyan.FFmpeg_*/ffmpeg-*/bin"):
            extra.append(str(bin_dir))
        # winget installs Deno at Packages/DenoLand.Deno_*/deno.exe (no /bin subdir)
        for deno_pkg in winget_pkgs.glob("DenoLand.Deno_*"):
            if (deno_pkg / "deno.exe").exists():
                extra.append(str(deno_pkg))
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")

_augment_path()

# Point yt-dlp at the local cookies file so it can authenticate to YouTube and
# bypass the anti-bot challenge. The pipeline reads YT_COOKIES_PATH at runtime.
_local_cookies = PROJECT_ROOT / "cookies.txt"
if _local_cookies.exists() and "YT_COOKIES_PATH" not in os.environ:
    os.environ["YT_COOKIES_PATH"] = str(_local_cookies)

# Load .env from the project root so the existing pipeline picks up keys.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from scripts.transcribe_with_frames import fetch_metadata, run_pipeline  # noqa: E402
from scripts.build_cheatsheet import build as build_cheatsheet  # noqa: E402
from scripts.build_illustrated_book import build as build_book  # noqa: E402
from bot.author import author_book, author_cheatsheet  # noqa: E402

WORK_ROOT = PROJECT_ROOT / "web_work"
WORK_ROOT.mkdir(exist_ok=True)


# --- in-memory job store ----------------------------------------------------

JobKind = Literal["cheatsheet", "book"]
JOBS: dict[str, dict[str, Any]] = {}


class CreateRequest(BaseModel):
    url: str = Field(..., min_length=10)
    kind: JobKind


# --- FastAPI app ------------------------------------------------------------

app = FastAPI(title="Cheatsheet API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"ok": "yes"}


@app.post("/api/generate")
async def create(req: CreateRequest, bg: BackgroundTasks) -> dict[str, str]:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id,
        "kind": req.kind,
        "url": req.url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": {"state": "queued"},
        "meta": None,
    }
    bg.add_task(_run_job, job_id)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.get("/api/files/{job_id}/pdf")
async def get_pdf(job_id: str) -> FileResponse:
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    pdf = WORK_ROOT / job_id / "output.pdf"
    if not pdf.exists():
        raise HTTPException(404, "pdf not ready")
    title = (j.get("meta") or {}).get("title") or "cheatsheet"
    safe = "".join(c if c.isalnum() or c in " ._-" else "_" for c in title)[:80]
    return FileResponse(pdf, media_type="application/pdf", filename=f"{safe}.pdf")


# --- background runner ------------------------------------------------------

async def _run_job(job_id: str) -> None:
    j = JOBS[job_id]
    work = WORK_ROOT / job_id
    work.mkdir(parents=True, exist_ok=True)

    progress_state = {"p": 0.05, "step": "Starting"}

    def emit(step: str, p: float | None = None) -> None:
        if p is not None:
            progress_state["p"] = max(progress_state["p"], min(0.95, p))
        progress_state["step"] = step
        j["status"] = {
            "state": "running",
            "step": step,
            "progress": round(progress_state["p"], 3),
        }

    def on_pipeline(msg: str) -> None:
        # Heuristic progress mapping based on what the pipeline emits.
        m = msg.lower()
        bumps = [
            ("download", 0.12),
            ("encode", 0.18),
            ("scene", 0.22),
            ("sampling fallback", 0.28),
            ("dedup", 0.32),
            ("splitting", 0.40),
            ("transcrib", 0.45),
        ]
        for kw, p in bumps:
            if kw in m:
                emit(msg, max(progress_state["p"], p))
                return
        # Transcribing chunk N/M — incrementally bump.
        if "chunk" in m and "/" in m:
            try:
                ratio = msg.split("chunk")[1].split("...")[0].strip()
                a, b = ratio.split("/")
                p = 0.45 + 0.25 * (int(a) / int(b))
                emit(msg, p)
                return
            except Exception:
                pass
        emit(msg)

    try:
        emit("Fetching video metadata", 0.05)
        meta = await asyncio.to_thread(fetch_metadata, j["url"])
        j["meta"] = {
            "video_id": meta["id"],
            "title": meta["title"],
            "duration_seconds": meta["duration"],
            "channel": "",
            "thumbnail_url": f"https://i.ytimg.com/vi/{meta['id']}/hqdefault.jpg",
        }

        extract_frames = j["kind"] == "book"
        result = await asyncio.to_thread(
            run_pipeline,
            j["url"],
            work,
            extract_frames=extract_frames,
            on_progress=on_pipeline,
        )

        emit("Authoring notes", 0.72)
        if j["kind"] == "cheatsheet":
            md_text = await asyncio.to_thread(
                author_cheatsheet,
                result["transcript_txt"],
                title_hint=j["meta"]["title"],
                duration_seconds=j["meta"]["duration_seconds"],
                on_progress=lambda m: emit(m, max(progress_state["p"], 0.72)),
            )
        else:
            md_text = await asyncio.to_thread(
                author_book,
                result["transcript_with_frames"],
                result["frames_index"],
                title_hint=j["meta"]["title"],
                duration_seconds=j["meta"]["duration_seconds"],
                on_progress=lambda m: emit(m, max(progress_state["p"], 0.72)),
            )

        md_path = work / "output.md"
        md_path.write_text(md_text, encoding="utf-8")

        emit("Rendering PDF", 0.92)
        pdf_path = work / "output.pdf"
        if j["kind"] == "cheatsheet":
            await asyncio.to_thread(
                build_cheatsheet, md_path, pdf_path, j["meta"]["title"]
            )
        else:
            await asyncio.to_thread(
                build_book,
                md_path,
                pdf_path,
                j["meta"]["title"],
                result["frames_dir"],
                None,
            )

        j["status"] = {
            "state": "done",
            "pdf_url": f"/api/files/{job_id}/pdf",
            "markdown": md_text,
            "meta": j["meta"],
        }
    except Exception as exc:
        j["status"] = {"state": "error", "message": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)
