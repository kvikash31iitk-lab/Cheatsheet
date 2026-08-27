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


def sanitize_filename(name: str) -> str:
    """Sanitize title into a safe Windows/Linux filename."""
    if not name:
        return "Document"
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', name).strip()
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
