#!/usr/bin/env python3
"""Universal CLI and Drag-and-Drop Markdown to PDF Rebuilder.

Usage:
  1. Single file:
     python scripts/rebuild_pdf.py path/to/cheatsheet.md

  2. With custom output path or title:
     python scripts/rebuild_pdf.py path/to/input.md path/to/output.pdf --title "My Course Title"

  3. Batch folder (e.g. all 23 videos in a playlist directory):
     python scripts/rebuild_pdf.py --folder web_work/playlist_jobs/<JOB_ID>
"""
import argparse
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.build_cheatsheet as bc
import scripts.build_illustrated_book as bb
import scripts.build_mcq_handbook as bm
import scripts.build_structured_notes as bsn


def render_md_file(md_path: Path, out_path: Path | None = None, title: str | None = None, kind: str = "cheatsheet") -> Path:
    if not md_path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    if out_path is None:
        out_path = md_path.with_suffix(".pdf")

    # Detect title if not specified
    if not title:
        try:
            with open(md_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
        except Exception:
            pass

    if kind == "book":
        bb.build(src=md_path, out=out_path, title=title)
    elif kind == "mcq":
        bm.build(src=md_path, out=out_path, title=title)
    elif kind == "structured_notes":
        bsn.build(md_path=md_path, pdf_path=out_path, title=title or "Structured Notes")
    elif kind == "cheatsheet_refined":
        from scripts.build_cheatsheet_refined import build as build_refined
        build_refined(md_path=md_path, pdf_path=out_path, title=title or "High-Yield Revision Cheatsheet")
    else:
        bc.build(src=md_path, out=out_path, title=title)

    return out_path


def main():
    parser = argparse.ArgumentParser(description="Rebuild PDF from Markdown")
    parser.add_argument("input", nargs="?", help="Path to input .md file")
    parser.add_argument("output", nargs="?", help="Path to output .pdf file (optional)")
    parser.add_argument("--kind", choices=["cheatsheet", "cheatsheet_refined", "book", "mcq", "structured_notes"], default="cheatsheet", help="Document kind")
    parser.add_argument("--title", help="Document title for header")
    parser.add_argument("--folder", help="Batch rebuild all .md files in this directory")

    args = parser.parse_args()

    if args.folder:
        folder = Path(args.folder)
        if not folder.is_dir():
            print(f"[ERROR] Folder not found: {folder}")
            sys.exit(1)
        
        md_files = list(folder.rglob("*.md"))
        print(f"=== Found {len(md_files)} Markdown files in {folder} ===")
        success = 0
        for idx, md_p in enumerate(md_files, 1):
            if md_p.name.startswith("transcript"):
                continue
            try:
                pdf_p = render_md_file(md_p, kind=args.kind)
                success += 1
                print(f"[{idx}/{len(md_files)}] Rendered: {pdf_p.name}")
            except Exception as e:
                print(f"[{idx}/{len(md_files)}] Failed {md_p.name}: {e}")
        print(f"\n[DONE] Successfully rendered {success} PDFs!")
        return

    if not args.input:
        print("Usage: python scripts/rebuild_pdf.py <input.md> [output.pdf] [--kind cheatsheet|book|mcq]")
        sys.exit(1)

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else None
    out_pdf = render_md_file(in_path, out_path, title=args.title, kind=args.kind)
    print(f"\n[SUCCESS] PDF Generated at: {out_pdf}")


if __name__ == "__main__":
    main()
