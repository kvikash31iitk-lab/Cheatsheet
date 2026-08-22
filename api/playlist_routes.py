"""API routes for batch playlist generation."""
from __future__ import annotations

import asyncio
import json
import re
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


@router.post("/retry/{job_id}")
async def retry_playlist(
    job_id: str,
    bg_tasks: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Retry failed videos for an existing playlist job."""
    job_dir = PLAYLIST_WORK_ROOT / job_id
    manifest_path = job_dir / "playlist_manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(404, "Playlist job manifest not found")

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        playlist_url = manifest_data.get("playlist_url")
        if not playlist_url:
            raise HTTPException(400, "Manifest missing playlist URL")

        # Reset failed items to allow retry while keeping completed ones
        items = manifest_data.get("items", {})
        for item_key, item_val in items.items():
            if item_val.get("status") == "failed":
                item_val["status"] = "pending"
                item_val.pop("error", None)

        manifest_data["status"] = "running"
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        req = PlaylistGenerateRequest(
            playlist_url=playlist_url,
            kind="cheatsheet",
            delay_seconds=5.0,
        )

        bg_tasks.add_task(_async_run_playlist, job_id, req)
        return {"id": job_id, "status": "retrying"}
    except Exception as exc:
        raise HTTPException(500, f"Failed to initiate retry: {exc}")



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

    def _safe_ep(t: str) -> float:
        if not t:
            return 999.0
        m = re.search(r'\b(?:class|ep|episode|part|lecture|lec|vol|v|#)[-:\s]*(\d+(?:\.\d+)?)\b', t, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        m2 = re.search(r'\b(?:class|part|lec|lecture)[-:\s]*(\d+)', t, re.IGNORECASE)
        if m2:
            try:
                return float(m2.group(1))
            except ValueError:
                pass
        return 999.0

    def _safe_topic(t: str) -> str:
        if not t:
            return ""
        cleaned = re.sub(r'\b(?:class|ep|episode|part|lecture|lec|vol|v|#)[-:\s]*\d+(?:\.\d+)?\b', '', t, flags=re.IGNORECASE)
        cleaned = re.sub(r'[\d_|\-–—:]+', ' ', cleaned)
        toks = [w.lower() for w in cleaned.split() if len(w) > 3 and w.lower() not in {"upsc", "epfo", "apfc", "acio", "complete", "course", "video", "hindi", "english"}]
        return " ".join(toks[:3]) if toks else ""

    for job_dir in sorted(PLAYLIST_WORK_ROOT.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if not job_dir.is_dir():
            continue
        manifest_path = job_dir / "playlist_manifest.json"
        if not manifest_path.is_file():
            continue

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            items_data = []
            for idx, (item_key, item_val) in enumerate(data.get("items", {}).items(), 1):
                res = item_val.get("result", {}) or {}
                pdf_str = res.get("pdf_path")
                has_pdf = bool(pdf_str and Path(pdf_str).is_file())
                if not has_pdf:
                    has_pdf = len(list((job_dir / item_key).glob("**/*.pdf"))) > 0

                items_data.append({
                    "item_key": item_key,
                    "title": res.get("title") or item_val.get("title") or item_key,
                    "status": item_val.get("status"),
                    "video_id": res.get("video_id"),
                    "has_pdf": has_pdf,
                    "error": item_val.get("error"),
                    "orig_idx": idx,
                })

            topic_order_map: dict[str, int] = {}
            for it in items_data:
                top = _safe_topic(it["title"])
                if top and top not in topic_order_map:
                    topic_order_map[top] = it["orig_idx"]

            items_data.sort(key=lambda x: (
                topic_order_map.get(_safe_topic(x["title"]), 0),
                _safe_ep(x["title"]),
                x["orig_idx"]
            ))

            results.append({
                "id": job_dir.name,
                "playlist_url": data.get("playlist_url"),
                "status": data.get("status", "completed"),
                "created_at": data.get("created_at"),
                "total_videos": data.get("total_videos", 0),
                "summary": data.get("summary"),
                "items": items_data,
            })
        except Exception as exc:
            print(f"[playlist_list_error] {job_dir.name}: {exc}", flush=True)

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


@router.get("/download/{job_id}/item/{item_key}")
async def download_item_pdf(
    job_id: str,
    item_key: str,
    user: User = Depends(current_user),
):
    """Serve individual video cheatsheet PDF for a playlist item."""
    from fastapi.responses import FileResponse
    job_dir = PLAYLIST_WORK_ROOT / job_id
    manifest_path = job_dir / "playlist_manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(404, "Playlist job manifest not found")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    item_val = data.get("items", {}).get(item_key)
    if not item_val:
        raise HTTPException(404, "Playlist video item not found")

    pdf_path = None
    res = item_val.get("result")
    if res and res.get("pdf_path"):
        p = Path(res["pdf_path"])
        if p.is_file():
            pdf_path = p

    if not pdf_path:
        candidates = list((job_dir / item_key).glob("**/*.pdf"))
        if candidates:
            pdf_path = candidates[0]

    if not pdf_path or not pdf_path.is_file():
        raise HTTPException(404, "Individual PDF file not found for this item")

    clean_name = f"cheatsheet_{item_key}.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=clean_name)


@router.get("/download/{job_id}/zip")
async def download_playlist_zip(
    job_id: str,
    user: User = Depends(current_user),
):
    """Bundle all generated master and individual PDFs/markdowns into a zip file."""
    import zipfile
    from fastapi.responses import FileResponse

    job_dir = PLAYLIST_WORK_ROOT / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, "Playlist job directory not found")

    zip_path = job_dir / f"playlist_cheatsheets_{job_id[:8]}.zip"

    # Always generate/refresh zip with surviving PDFs and markdowns
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in job_dir.glob("**/*"):
            if file.is_file() and file.name != zip_path.name and not file.name.endswith(".tmp"):
                if file.suffix == ".pdf":
                    # Clean filename for individual vs master PDF inside PDF_Cheatsheets folder
                    if "Consolidated" in file.parts or file.name == "master_cheatsheet.pdf":
                        arc_name = "PDF_Cheatsheets/00_Master_Consolidated_Cheatsheet.pdf"
                    else:
                        parent_name = file.parent.name
                        arc_name = f"PDF_Cheatsheets/{parent_name}_{file.name}"
                    zf.write(file, arcname=arc_name)
                elif file.suffix in (".md", ".txt", ".json"):
                    rel = file.relative_to(job_dir)
                    zf.write(file, arcname=f"Source_Data/{rel}")

    if not zip_path.is_file():
        raise HTTPException(404, "Failed to create ZIP package")

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"playlist_cheatsheets_{job_id[:8]}.zip",
    )





