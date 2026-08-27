"""Helper to automatically save all generated PDFs, Markdown notes, and ZIP bundles
into the root 'saved files' directory with clean, human-readable titles.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAVED_FILES_DIR = PROJECT_ROOT / "saved files"
SAVED_FILES_DIR.mkdir(parents=True, exist_ok=True)

KIND_LABELS = {
    "cheatsheet": "Cheatsheet",
    "mcq": "Solved MCQs",
    "book": "Illustrated Book",
    "marathon": "Handbook",
    "playlist": "Playlist",
}


def clean_human_title(name: str) -> str:
    """Extract a clean, human-readable topic name from raw video titles."""
    if not name or name.startswith("http"):
        return "Lecture Note"
    
    t = name
    # Strip emojis and non-ascii
    t = re.sub(r'[^\x00-\x7F]+', ' ', t)
    # Remove leading numbering like '26 '
    t = re.sub(r'^\d+\s+', '', t)
    # Remove common prefix boilerplates
    t = re.sub(r'^UPSC\s+EPFO\s+(?:AO/?EO\s*(?:&|and)?\s*)?(?:APFC\s*)?\|\s*', '', t, flags=re.I)
    t = re.sub(r'^General Accounting Principles\s*\|\s*', '', t, flags=re.I)
    t = re.sub(r'^EPFO Complete Course\s*\|\s*', '', t, flags=re.I)
    # Remove trailing teacher / channel tags
    t = re.sub(r'\|\s*(?:By\s+)?(?:Anurag\s*Sir|EPFO Exam Preparation|EduTap|Civilstap|Anuj Jindal|MBA Pathshala|MBA Wallah|Vijay Sir|Smriti Shah|Raj Shamani).*$', '', t, flags=re.I)
    t = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', t)
    t = re.sub(r'_+', '_', t).strip(' _.-|')
    return t if t else name[:60]


def sanitize_filename(name: str) -> str:
    """Sanitize title into a safe Windows/Linux filename."""
    if not name:
        return "Document"
    # If the title is just a raw YouTube video ID (e.g. 11 characters alphanumeric/hyphen/underscore)
    cleaned = clean_human_title(name)
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', cleaned).strip()
    cleaned = re.sub(r'_+', '_', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:110].strip(" _.")


def save_generated_artifacts(
    pdf_path: Path | str | None = None,
    md_path: Path | str | None = None,
    zip_path: Path | str | None = None,
    title: str | None = None,
    kind: str = "cheatsheet",
) -> dict[str, Path]:
    """Save copies of generated PDF, Markdown, and ZIP files into the root 'saved files' folder."""
    try:
        SAVED_FILES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    saved: dict[str, Path] = {}
    clean_title = sanitize_filename(title or "Document") or "Document"
    label = KIND_LABELS.get(kind.lower(), kind.capitalize())

    # 1. Save PDF
    if pdf_path:
        p_src = Path(pdf_path)
        if p_src.exists() and p_src.is_file():
            dst_name = f"{clean_title} - {label}.pdf"
            dst_p = SAVED_FILES_DIR / dst_name
            try:
                shutil.copy2(p_src, dst_p)
                saved["pdf"] = dst_p
                print(f"[saved-files] Saved PDF -> {dst_p.name}", flush=True)
            except Exception as e:
                print(f"[saved-files] Error copying PDF: {e}", flush=True)

    # 2. Save Markdown
    if md_path:
        m_src = Path(md_path)
        if m_src.exists() and m_src.is_file():
            dst_name = f"{clean_title} - {label}.md"
            dst_m = SAVED_FILES_DIR / dst_name
            try:
                shutil.copy2(m_src, dst_m)
                saved["markdown"] = dst_m
                print(f"[saved-files] Saved Markdown -> {dst_m.name}", flush=True)
            except Exception as e:
                print(f"[saved-files] Error copying Markdown: {e}", flush=True)

    # 3. Save ZIP (Playlist Bundles)
    if zip_path:
        z_src = Path(zip_path)
        if z_src.exists() and z_src.is_file():
            dst_name = f"{clean_title}.zip" if clean_title.lower().endswith(".zip") else f"{clean_title} - Playlist.zip"
            dst_z = SAVED_FILES_DIR / dst_name
            try:
                shutil.copy2(z_src, dst_z)
                saved["zip"] = dst_z
                print(f"[saved-files] Saved ZIP -> {dst_z.name}", flush=True)
            except Exception as e:
                print(f"[saved-files] Error copying ZIP: {e}", flush=True)

    return saved
