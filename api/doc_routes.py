"""Document, Book & Handwritten Notes Cheatsheet Engine Routes.

Provides endpoints for:
- POST /api/docs/inspect: Pre-flight inspect an uploaded PDF or image (page count, TOC chapters, text density, OCR type)
- POST /api/docs/generate: Ingests digital book, scanned handout, or handwritten notes,
  extracts knowledge via PyMuPDF or Gemini Multimodal Vision, authors high-density UPSC revision markdown,
  and compiles a publication ReportLab PDF.
- GET /api/docs/demo: Preloaded Bipan Chandra demo for 1-click test in the UI.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import fitz  # PyMuPDF
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import SyncSessionLocal, get_session
from api.deps import current_user
from api.models import Generation, User
from bot.author import _author_gemini, REFINED_CHEATSHEET_SYSTEM
from scripts.build_cheatsheet_refined import build as build_cheatsheet_refined

doc_router = APIRouter(prefix="/api/docs", tags=["documents"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
WORK_ROOT = PROJECT_ROOT / "web_work"
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def _transcribe_pages_gemini_vision(image_bytes_list: list[bytes], custom_prompt: str = "") -> str:
    """Use Gemini Multimodal Vision to transcribe handwritten notes or scanned pages."""
    import requests
    from bot.config import GEMINI_API_KEY, GEMINI_API_KEYS

    keys = [k.strip() for k in (GEMINI_API_KEYS or [GEMINI_API_KEY]) if k and k.strip()]
    models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]

    parts: list[dict[str, Any]] = []
    for b in image_bytes_list:
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": base64.b64encode(b).decode("utf-8")
            }
        })

    prompt_text = custom_prompt or (
        "You are an expert handwritten notes & document transcription engine.\n"
        "Carefully transcribe all handwritten text, annotations, diagrams, and equations from these pages.\n"
        "Retain 100% of facts, dates, names, formulas, and structural relationships.\n"
        "Output structured Markdown with clear headings, bullet points, and tables where diagrams exist."
    )
    parts.append({"text": prompt_text})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 6000}
    }

    for key in keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=45)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content_parts = candidates[0].get("content", {}).get("parts", [])
                        texts = [p.get("text", "") for p in content_parts if "text" in p]
                        if texts:
                            return "\n".join(texts)
            except Exception:
                continue

    return ""


def _inspect_pdf_file(pdf_path: Path) -> dict[str, Any]:
    """Inspect a PDF: page count, TOC chapters, text density, and detected document type."""
    doc = fitz.open(pdf_path)
    page_count = len(doc)

    # Sample text density
    sample_pages = min(page_count, 8)
    total_chars = 0
    preview_snippet = ""
    for p in range(sample_pages):
        txt = doc[p].get_text()
        total_chars += len(txt)
        if not preview_snippet and txt.strip():
            preview_snippet = txt.strip()[:400]

    avg_chars = total_chars / max(1, sample_pages)
    doc_type = "digital" if avg_chars > 250 else "scanned"

    # 1. Extract digital electronic TOC bookmarks if present
    raw_toc = doc.get_toc()
    chapters: list[dict[str, Any]] = []

    if raw_toc:
        for i, item in enumerate(raw_toc):
            lvl, title, start_p = item[0], item[1].strip(), item[2]
            if lvl in (1, 2) and title:
                # Calculate end page
                end_p = page_count
                for next_item in raw_toc[i + 1 :]:
                    if next_item[0] <= lvl:
                        end_p = max(start_p, next_item[2] - 1)
                        break
                chapters.append({
                    "index": len(chapters) + 1,
                    "level": lvl,
                    "title": title,
                    "start_page": max(1, start_p),
                    "end_page": min(page_count, max(start_p, end_p)),
                    "page_span": f"pp. {start_p}–{end_p}",
                })

    # 2. If no digital bookmarks, scan for printed UNIT / CHAPTER / BLOCK / MODULE headings
    if not chapters:
        import re
        detected_units: list[tuple[int, str]] = []
        for p in range(page_count):
            try:
                txt = doc[p].get_text()
            except Exception:
                continue
            lines = [l.strip() for l in txt.split("\n") if l.strip()]
            for idx, l in enumerate(lines[:10]):
                m = re.match(r"^(?:UNIT|CHAPTER|BLOCK|MODULE|LESSON)\s*[-:]?\s*(\d+|[IVX]+)\b", l, re.IGNORECASE)
                if m:
                    # Skip table of contents pages in the very beginning
                    if p < 10 and any(w in txt.lower()[:250] for w in ["contents", "table of contents"]):
                        continue
                    clean_h = re.sub(r"\s+", " ", l).strip()
                    if idx + 1 < len(lines) and 3 < len(lines[idx + 1]) < 60:
                        sub = re.sub(r"\s+", " ", lines[idx + 1]).strip()
                        clean_h += f": {sub}"
                    # Ensure minimum 5 pages spacing between chapters
                    if not detected_units or (p + 1 - detected_units[-1][0] >= 5):
                        detected_units.append((p + 1, clean_h))
                    break

        if len(detected_units) >= 2:
            for i, (sp, t) in enumerate(detected_units):
                ep = detected_units[i + 1][0] - 1 if i + 1 < len(detected_units) else page_count
                chapters.append({
                    "index": i + 1,
                    "level": 1,
                    "title": t[:80],
                    "start_page": sp,
                    "end_page": min(page_count, max(sp, ep)),
                    "page_span": f"pp. {sp}–{ep}",
                })

    # 3. If still no chapters and document is large (> 25 pages), auto-partition into 20-page parts
    # so the user can always batch process the entire document without hitting single-prompt limits!
    if not chapters and page_count > 25:
        chunk_size = 20
        chunk_idx = 1
        for sp in range(1, page_count + 1, chunk_size):
            ep = min(page_count, sp + chunk_size - 1)
            chapters.append({
                "index": chunk_idx,
                "level": 1,
                "title": f"Part {chunk_idx}: Pages {sp}–{ep}",
                "start_page": sp,
                "end_page": ep,
                "page_span": f"pp. {sp}–{ep}",
            })
            chunk_idx += 1

    return {
        "page_count": page_count,
        "doc_type": doc_type,
        "has_toc": len(chapters) > 0,
        "chapters": chapters,
        "preview_text": preview_snippet,
    }


@doc_router.post("/inspect")
async def inspect_document(
    file: UploadFile = File(..., description="PDF or image of book/notes to inspect"),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Upload and pre-flight inspect a document for chapters, type, and page count."""
    file_id = uuid.uuid4().hex[:12]
    ext = Path(file.filename or "upload.pdf").suffix.lower()
    if not ext:
        ext = ".pdf"
    clean_name = f"{file_id}_{Path(file.filename or 'upload').stem}{ext}"
    dest_path = UPLOAD_DIR / clean_name

    contents = await file.read()
    dest_path.write_bytes(contents)
    file_size_mb = round(len(contents) / (1024 * 1024), 2)

    if ext == ".pdf":
        try:
            info = _inspect_pdf_file(dest_path)
        except Exception as e:
            raise HTTPException(400, f"Failed to read PDF file: {e}") from None
    else:
        # Image file (PNG, JPG, WEBP)
        info = {
            "page_count": 1,
            "doc_type": "handwritten",
            "has_toc": False,
            "chapters": [],
            "preview_text": f"Image file ({file.filename}) ready for handwritten transcription.",
        }

    return {
        "file_id": clean_name,
        "filename": file.filename,
        "file_size_mb": file_size_mb,
        **info,
    }


@doc_router.get("/demo")
async def demo_bipan_chandra(
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Inspect the pre-downloaded Bipan Chandra test textbook."""
    pdf_path = PROJECT_ROOT / "data" / "test_docs" / "bipan_chandra_india_since_independence.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, "Demo file not found.")

    info = _inspect_pdf_file(pdf_path)
    return {
        "file_id": "__demo_bipan_chandra__",
        "filename": "GS1_PI_India_Since_Independence_(Bipan_Chandra).pdf",
        "file_size_mb": round(pdf_path.stat().st_size / (1024 * 1024), 2),
        **info,
    }


def _run_document_pipeline(
    job_id: str,
    file_path: Path,
    title: str,
    doc_type: str,
    chapter_title: Optional[str],
    start_page: int,
    end_page: int,
    output_kind: str,
    exam_target: str,
) -> None:
    """Synchronous worker thread that executes extraction, authoring, and PDF compilation."""
    work_dir = WORK_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    def update_job(step: str, progress: float, status: str = "running", md: str = "", pdf: str = ""):
        with SyncSessionLocal() as session:
            stmt = select(Generation).where(Generation.id == job_id)
            row = session.execute(stmt).scalar_one_or_none()
            if row:
                row.step = step
                row.progress = progress
                row.status = status
                if md:
                    row.markdown = md
                if pdf:
                    row.pdf_path = pdf
                if status == "complete":
                    row.completed_at = datetime.now(timezone.utc)
                session.commit()

    try:
        update_job("Analyzing & extracting document content...", 0.15)
        extracted_text = ""

        is_pdf = file_path.suffix.lower() == ".pdf"
        if is_pdf:
            doc = fitz.open(file_path)
            total_pages = len(doc)
            sp = max(0, start_page - 1)
            ep = min(total_pages, end_page)

            # Check if this range requires vision (handwritten or pure images)
            needs_vision = (doc_type == "handwritten")
            if not needs_vision:
                # Test text extraction
                sample_txt = ""
                for p in range(sp, min(ep, sp + 3)):
                    sample_txt += doc[p].get_text()
                if len(sample_txt.strip()) < 150:
                    needs_vision = True

            if needs_vision:
                update_job(f"Transcribing {ep - sp} pages via Gemini Multimodal Vision...", 0.30)
                image_bytes_list: list[bytes] = []
                # Cap vision batch at 15 pages per run for high fidelity
                for p in range(sp, min(ep, sp + 15)):
                    pix = doc[p].get_pixmap(dpi=150)
                    image_bytes_list.append(pix.tobytes("png"))

                transcription = _transcribe_pages_gemini_vision(image_bytes_list)
                extracted_text = transcription
            else:
                update_job(f"Extracting vector text from pages {sp + 1} to {ep}...", 0.30)
                for p in range(sp, ep):
                    txt = doc[p].get_text()
                    extracted_text += f"\n=== PAGE {p + 1} ===\n{txt}"
        else:
            # Single image file
            update_job("Transcribing image notes via Gemini Multimodal Vision...", 0.30)
            img_bytes = file_path.read_bytes()
            transcription = _transcribe_pages_gemini_vision([img_bytes])
            extracted_text = transcription

        if not extracted_text.strip():
            raise RuntimeError("Could not extract any legible text from the selected document range.")

        # Authoring step
        update_job("Synthesizing high-density UPSC revision notes with Gemini...", 0.55)
        doc_label = chapter_title or title or file_path.stem
        prompt = f"""Below is the extracted source material from "{doc_label}" (pages {start_page} to {end_page}):
\"\"\"{extracted_text[:35000]}\"\"\"

Convert this entire source material into an exhaustive, high-density REVISION CHEATSHEET ('Seedhi Baat No Bakwaas') tailored for {exam_target.upper() if exam_target else 'UPSC CSE GS & OPTIONAL'}.
Follow these strict directives:
1. PURE FACTUAL DENSITY: Zero conversational pleasantries, zero filler.
2. CHRONOLOGY & EVOLUTION: Extract every statutory act, commission, committee, date, constitutional article, case law, and timeline in chronological order.
3. COMPARATIVE MATRIX TABLES: Formulate comparison tables whenever two or more bodies, policies, commissions, or concepts overlap.
4. 2-COLUMN KEY FACT GRIDS: Group short facts, dates, names, ratios, thresholds, and provisions into crisp bullet lists under clean headers.
5. CONCEPTUAL ANALYSIS & DIMENSIONS: Explain the core analytical rationale (causes, impacts, constitutional importance).
6. EXAM TRAPS & PITFALLS:
   > [!warning] Exam Trap: [Specify common pitfalls, confusing terminology, or tricky MCQ traps]
7. QUICK MNEMONICS:
   > [!tip] Mnemonic: [Helpful memory anchors where applicable]
"""

        md_text = _author_gemini(
            system=REFINED_CHEATSHEET_SYSTEM,
            user=prompt,
            max_tokens=6500,
        )

        out_md = work_dir / "output.md"
        out_md.write_text(md_text, encoding="utf-8")

        # PDF Compilation step
        update_job("Rendering ReportLab publication PDF...", 0.85)
        out_pdf = work_dir / "output.pdf"
        clean_title = (chapter_title or title or file_path.stem).strip()
        build_cheatsheet_refined(
            out_md,
            out_pdf,
            title=f"Cheatsheet: {clean_title}"
        )

        # Copy to Desktop if directory exists for instant local access
        desktop_dir = Path(r"C:\Users\HP\Desktop\Civils Tap\Documents")
        try:
            desktop_dir.mkdir(parents=True, exist_ok=True)
            safe_fname = "".join(c if c.isalnum() or c in " ._-" else "_" for c in clean_title).strip()[:80]
            shutil.copy2(out_pdf, desktop_dir / f"{safe_fname}.pdf")
        except Exception:
            pass

        update_job("Cheatsheet generated successfully!", 1.0, status="complete", md=md_text, pdf=str(out_pdf))

    except Exception as exc:
        update_job(f"Generation failed: {exc}", 0.0, status="error")


@doc_router.post("/generate")
async def generate_document_cheatsheet(
    bg: BackgroundTasks,
    file_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    title: Optional[str] = Form(None),
    doc_type: str = Form("auto"),
    chapter_title: Optional[str] = Form(None),
    start_page: Optional[int] = Form(None),
    end_page: Optional[int] = Form(None),
    output_kind: str = Form("cheatsheet"),
    exam_target: str = Form("UPSC CSE"),
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Queue a cheatsheet generation job from an uploaded file or pre-inspected file_id."""
    target_path: Optional[Path] = None

    if file_id == "__demo_bipan_chandra__":
        target_path = PROJECT_ROOT / "data" / "test_docs" / "bipan_chandra_india_since_independence.pdf"
        display_name = "Bipan Chandra - India Since Independence"
    elif file_id:
        target_path = UPLOAD_DIR / file_id
        display_name = file_id
    elif file:
        f_id = uuid.uuid4().hex[:12]
        ext = Path(file.filename or "upload.pdf").suffix.lower() or ".pdf"
        clean_name = f"{f_id}_{Path(file.filename or 'upload').stem}{ext}"
        target_path = UPLOAD_DIR / clean_name
        contents = await file.read()
        target_path.write_bytes(contents)
        display_name = file.filename or "Document"
    else:
        raise HTTPException(400, "Either file or file_id must be provided.")

    if not target_path.exists():
        raise HTTPException(404, "Document file not found on server.")

    # Determine default page bounds if not given
    sp = start_page or 1
    ep = end_page or 25
    if not end_page and target_path.suffix.lower() == ".pdf":
        try:
            d = fitz.open(target_path)
            ep = min(len(d), 25)
        except Exception:
            ep = 25

    job_title = title or (f"{chapter_title} ({display_name})" if chapter_title else f"{display_name} Cheatsheet")

    gen = Generation(
        id=uuid.uuid4().hex,
        user_id=user.id,
        kind="cheatsheet",
        url=f"doc://{display_name}",
        title=job_title,
        status="queued",
        step="Document queued for high-density cheatsheet generation",
        progress=0.05,
        was_free=False,
        cost_paise=0,
        features=json.dumps(["summary", "matrices", "fact_grids", "traps"]),
    )
    s.add(gen)
    await s.commit()

    # Dispatch worker to background thread
    bg.add_task(
        _run_document_pipeline,
        job_id=gen.id,
        file_path=target_path,
        title=job_title,
        doc_type=doc_type,
        chapter_title=chapter_title,
        start_page=sp,
        end_page=ep,
        output_kind=output_kind,
        exam_target=exam_target,
    )

    return {"id": gen.id, "title": gen.title or job_title}


# ==============================================================================
# BOOK BATCH PROCESSING ENGINE (LIKE PLAYLIST BATCH GENERATION)
# ==============================================================================

BOOK_BATCH_WORK_ROOT = WORK_ROOT / "book_batch_jobs"
BOOK_BATCH_WORK_ROOT.mkdir(parents=True, exist_ok=True)
_book_batch_jobs: dict[str, dict[str, Any]] = {}


class ChapterItemSpec(BaseModel):
    index: int
    title: str
    start_page: int
    end_page: int
    page_span: Optional[str] = None


class BookBatchRequest(BaseModel):
    file_id: str
    book_title: str
    chapters: list[ChapterItemSpec]
    concurrency: int = 2
    exam_target: str = "UPSC CSE"


def _async_run_book_batch(
    batch_id: str,
    file_path: Path,
    book_title: str,
    chapters: list[dict[str, Any]],
    concurrency: int,
    exam_target: str,
) -> None:
    """Asynchronous worker that processes multiple chapters concurrently with live manifest updates."""
    job_dir = BOOK_BATCH_WORK_ROOT / batch_id
    job_dir.mkdir(parents=True, exist_ok=True)
    chapters_out_dir = job_dir / "chapters"
    chapters_out_dir.mkdir(parents=True, exist_ok=True)

    safe_book_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in book_title).strip()[:70] or "Book_Cheatsheets"
    desktop_book_dir = Path(r"C:\Users\HP\Desktop\Civils Tap") / safe_book_title
    try:
        desktop_book_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    manifest_path = job_dir / "manifest.json"

    items_dict: dict[str, dict[str, Any]] = {}
    for c in chapters:
        k = str(c["index"])
        items_dict[k] = {
            "index": c["index"],
            "title": c["title"],
            "start_page": c["start_page"],
            "end_page": c["end_page"],
            "page_span": c.get("page_span") or f"pp. {c['start_page']}–{c['end_page']}",
            "status": "pending",
            "step": "Queued",
            "pdf_url": None,
            "error": None,
        }

    manifest_data: dict[str, Any] = {
        "id": batch_id,
        "book_title": book_title,
        "status": "running",
        "total_chapters": len(chapters),
        "completed_count": 0,
        "failed_count": 0,
        "desktop_folder": str(desktop_book_dir),
        "items": items_dict,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _book_batch_jobs[batch_id] = manifest_data
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    def save_manifest():
        try:
            manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    max_workers = max(1, min(concurrency, 3))

    def process_one_chapter(item_key: str, chap: dict[str, Any]):
        if _book_batch_jobs.get(batch_id, {}).get("stopped"):
            return

        items_dict[item_key]["status"] = "running"
        items_dict[item_key]["step"] = "Extracting text..."
        save_manifest()

        try:
            doc = fitz.open(file_path)
            sp = max(0, chap["start_page"] - 1)
            ep = min(len(doc), chap["end_page"])

            extracted_text = ""
            for p in range(sp, ep):
                extracted_text += f"\n=== PAGE {p + 1} ===\n" + doc[p].get_text()

            if not extracted_text.strip():
                raise RuntimeError("No legible text extracted.")

            items_dict[item_key]["step"] = "Synthesizing with Gemini..."
            save_manifest()

            prompt = f"""Below is the extracted source material from Chapter: "{chap['title']}" of "{book_title}" (pages {chap['start_page']} to {chap['end_page']}):
\"\"\"{extracted_text[:35000]}\"\"\"

Convert this entire chapter into an exhaustive, high-density REVISION CHEATSHEET ('Seedhi Baat No Bakwaas') for {exam_target.upper()}.
Directives:
1. PURE FACTUAL DENSITY: Zero conversational pleasantries.
2. Chronology, acts, commissions, and timeline dates.
3. Comparative Matrix Tables for overlapping concepts.
4. 2-Column Fact Grids for quick memorization.
5. Conceptual analysis & constitutional/institutional rationale.
6. Exam Traps & Pitfalls:
   > [!warning] Exam Trap: ...
7. Quick Mnemonics:
   > [!tip] Mnemonic: ...
"""

            md_text = _author_gemini(
                system=REFINED_CHEATSHEET_SYSTEM,
                user=prompt,
                max_tokens=6500,
            )

            items_dict[item_key]["step"] = "Rendering publication PDF..."
            save_manifest()

            clean_chap_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in chap["title"]).strip()[:60]
            out_pdf = chapters_out_dir / f"Chapter_{chap['index']:02d}_{clean_chap_title}.pdf"
            out_md = chapters_out_dir / f"Chapter_{chap['index']:02d}_{clean_chap_title}.md"
            out_md.write_text(md_text, encoding="utf-8")

            build_cheatsheet_refined(
                out_md,
                out_pdf,
                title=f"{chap['title']} ({book_title[:30]})"
            )

            try:
                dest_desktop_pdf = desktop_book_dir / f"Chapter {chap['index']:02d} - {clean_chap_title}.pdf"
                shutil.copy2(out_pdf, dest_desktop_pdf)
            except Exception:
                pass

            items_dict[item_key]["status"] = "complete"
            items_dict[item_key]["step"] = "Complete"
            items_dict[item_key]["pdf_path"] = str(out_pdf)
            items_dict[item_key]["pdf_url"] = f"/api/docs/batch/download/{batch_id}/{chap['index']}"
            manifest_data["completed_count"] += 1
            save_manifest()

        except Exception as err:
            items_dict[item_key]["status"] = "failed"
            items_dict[item_key]["step"] = "Failed"
            items_dict[item_key]["error"] = str(err)
            manifest_data["failed_count"] += 1
            save_manifest()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for c in chapters:
            k = str(c["index"])
            futures.append(executor.submit(process_one_chapter, k, c))
        for f in futures:
            try:
                f.result()
            except Exception:
                pass

    if _book_batch_jobs.get(batch_id, {}).get("stopped"):
        manifest_data["status"] = "stopped"
    else:
        manifest_data["status"] = "complete"
    save_manifest()


@doc_router.post("/batch/generate")
async def generate_book_batch(
    req: BookBatchRequest,
    bg: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Start batch processing of multiple chapters from a book (like YouTube playlist generation)."""
    if req.file_id == "__demo_bipan_chandra__":
        target_path = PROJECT_ROOT / "data" / "test_docs" / "bipan_chandra_india_since_independence.pdf"
    else:
        target_path = UPLOAD_DIR / req.file_id

    if not target_path.exists():
        raise HTTPException(404, "Source book file not found.")

    if not req.chapters:
        raise HTTPException(400, "No chapters selected for batch processing.")

    batch_id = uuid.uuid4().hex[:12]

    bg.add_task(
        _async_run_book_batch,
        batch_id=batch_id,
        file_path=target_path,
        book_title=req.book_title,
        chapters=[c.dict() for c in req.chapters],
        concurrency=req.concurrency,
        exam_target=req.exam_target,
    )

    return {
        "id": batch_id,
        "batch_id": batch_id,
        "book_title": req.book_title,
        "total_chapters": len(req.chapters),
        "status": "queued",
    }


@doc_router.get("/batch/status/{batch_id}")
async def get_book_batch_status(
    batch_id: str,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Get real-time status and manifest for a running book batch job."""
    # Check memory first
    if batch_id in _book_batch_jobs:
        return _book_batch_jobs[batch_id]

    # Fall back to disk
    manifest_path = BOOK_BATCH_WORK_ROOT / batch_id / "manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            _book_batch_jobs[batch_id] = data
            return data
        except Exception:
            pass

    raise HTTPException(404, "Book batch job not found.")


@doc_router.post("/batch/stop/{batch_id}")
async def stop_book_batch(
    batch_id: str,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Halt an in-progress book batch job."""
    if batch_id in _book_batch_jobs:
        _book_batch_jobs[batch_id]["stopped"] = True
        _book_batch_jobs[batch_id]["status"] = "stopped"

    manifest_path = BOOK_BATCH_WORK_ROOT / batch_id / "manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["status"] = "stopped"
            manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    return {"id": batch_id, "status": "stopped"}


@doc_router.get("/batch/download/{batch_id}/{chapter_index}")
async def download_batch_chapter(
    batch_id: str,
    chapter_index: int,
    user: User = Depends(current_user),
) -> FileResponse:
    """Download an individual compiled chapter PDF from a batch job."""
    job_dir = BOOK_BATCH_WORK_ROOT / batch_id / "chapters"
    matches = list(job_dir.glob(f"Chapter_{chapter_index:02d}_*.pdf"))
    if not matches or not matches[0].exists():
        raise HTTPException(404, "Chapter PDF not found or not ready yet.")

    pdf_file = matches[0]
    return FileResponse(
        str(pdf_file),
        media_type="application/pdf",
        filename=pdf_file.name,
    )


@doc_router.get("/batch/download-all/{batch_id}")
async def download_batch_all_zip(
    batch_id: str,
    user: User = Depends(current_user),
) -> FileResponse:
    """Bundle all completed chapter PDFs from the batch into a single ZIP file."""
    job_dir = BOOK_BATCH_WORK_ROOT / batch_id
    chapters_dir = job_dir / "chapters"
    if not chapters_dir.is_dir():
        raise HTTPException(404, "Batch output directory not found.")

    pdf_files = sorted(list(chapters_dir.glob("*.pdf")))
    if not pdf_files:
        raise HTTPException(404, "No completed chapter PDFs found to zip.")

    zip_path = job_dir / f"{batch_id}_cheatsheets.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in pdf_files:
            zf.write(p, arcname=p.name)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"Book_Cheatsheets_Batch_{batch_id}.zip",
    )


@doc_router.get("/batch/list")
async def list_book_batches(
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    """List all book batch generation jobs from memory and disk."""
    results: list[dict[str, Any]] = []
    seen_ids = set()

    for batch_id, data in _book_batch_jobs.items():
        results.append(data)
        seen_ids.add(batch_id)

    if BOOK_BATCH_WORK_ROOT.is_dir():
        for job_folder in BOOK_BATCH_WORK_ROOT.iterdir():
            if job_folder.is_dir() and job_folder.name not in seen_ids:
                manifest_path = job_folder / "manifest.json"
                if manifest_path.is_file():
                    try:
                        d = json.loads(manifest_path.read_text(encoding="utf-8"))
                        results.append(d)
                        seen_ids.add(job_folder.name)
                    except Exception:
                        pass

    results.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return results


