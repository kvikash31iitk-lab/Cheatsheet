"""API routes for batch playlist generation."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import AsyncSessionLocal, get_session
from api.deps import User, current_user
from api.youtube_urls import validate_public_youtube_url
from scripts.run_playlist_job import run_playlist_job

router = APIRouter(prefix="/api/playlist", tags=["playlist"])

PLAYLIST_WORK_ROOT = Path(__file__).resolve().parent.parent / "web_work" / "playlist_jobs"
PLAYLIST_WORK_ROOT.mkdir(parents=True, exist_ok=True)

# In-memory status store for playlist jobs
_playlist_jobs: dict[str, dict[str, Any]] = {}


class PlaylistGenerateRequest(BaseModel):
    playlist_url: str
    kind: str = "cheatsheet"
    delay_seconds: float = 5.0
    max_videos: Optional[int] = None
    features: Optional[list[str]] = None


def _async_run_playlist(job_id: str, req: PlaylistGenerateRequest) -> None:
    job_dir = PLAYLIST_WORK_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _playlist_jobs[job_id] = {
        "id": job_id,
        "playlist_url": req.playlist_url,
        "kind": req.kind,
        "status": "running",
        "progress": "Extracting playlist information...",
        "summary": None,
        "error": None,
    }

    def on_progress(msg: str) -> None:
        if job_id in _playlist_jobs:
            _playlist_jobs[job_id]["progress"] = msg

    try:
        summary = run_playlist_job(
            req.playlist_url,
            kind=req.kind,
            out_dir=job_dir,
            delay_seconds=req.delay_seconds,
            max_videos=req.max_videos,
            features=req.features or [],
            continue_on_error=True,
            progress=on_progress,
        )
        _playlist_jobs[job_id]["status"] = "complete"
        _playlist_jobs[job_id]["summary"] = summary
        _playlist_jobs[job_id]["progress"] = "Completed successfully"

    except Exception as exc:
        import traceback
        traceback.print_exc()
        _playlist_jobs[job_id]["status"] = "error"
        _playlist_jobs[job_id]["error"] = str(exc)
        _playlist_jobs[job_id]["progress"] = f"Failed: {exc}"
        manifest_path = job_dir / "playlist_manifest.json"
        try:
            manifest_path.write_text(json.dumps({
                "status": "error",
                "error": str(exc),
                "progress": f"Failed: {exc}"
            }), encoding="utf-8")
        except Exception:
            pass




@router.post("/generate")
async def generate_playlist(
    req: PlaylistGenerateRequest,
    bg_tasks: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    bg_tasks.add_task(_async_run_playlist, job_id, req)
    return {"id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def get_playlist_status(
    job_id: str,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    job = _playlist_jobs.get(job_id)
    if not job:
        # Check disk manifest if in-memory missing
        job_dir = PLAYLIST_WORK_ROOT / job_id
        manifest_path = job_dir / "playlist_manifest.json"
        if manifest_path.is_file():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                return {
                    "id": job_id,
                    "status": data.get("status", "unknown"),
                    "summary": data.get("summary"),
                    "manifest": data,
                }
            except Exception:
                pass
        raise HTTPException(404, "Playlist job not found")

    # Read live manifest if available
    job_dir = PLAYLIST_WORK_ROOT / job_id
    manifest_path = job_dir / "playlist_manifest.json"
    manifest_data = None
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "summary": job["summary"],
        "error": job["error"],
        "manifest": manifest_data,
    }


@router.get("/list")
async def list_playlists(
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    """Scan PLAYLIST_WORK_ROOT for saved playlist jobs."""
    results = []
    if not PLAYLIST_WORK_ROOT.exists():
        return []

    for job_dir in sorted(PLAYLIST_WORK_ROOT.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if not job_dir.is_dir():
            continue
        manifest_path = job_dir / "playlist_manifest.json"
        if manifest_path.is_file():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                results.append({
                    "id": job_dir.name,
                    "playlist_url": data.get("playlist_url"),
                    "status": data.get("status", "completed"),
                    "created_at": data.get("created_at"),
                    "total_videos": data.get("total_videos", 0),
                    "summary": data.get("summary"),
                    "items_count": len(data.get("items", {})),
                })
            except Exception:
                pass
    return results


@router.get("/download/{job_id}/master")
async def download_master_pdf(
    job_id: str,
    user: User = Depends(current_user),
):
    """Serve master consolidated PDF for a playlist job."""
    from fastapi.responses import FileResponse
    master_pdf = PLAYLIST_WORK_ROOT / job_id / "Consolidated" / "master_cheatsheet.pdf"
    if not master_pdf.is_file():
        raise HTTPException(404, "Master PDF not found")
    return FileResponse(master_pdf, media_type="application/pdf", filename=f"master_cheatsheet_{job_id[:8]}.pdf")

