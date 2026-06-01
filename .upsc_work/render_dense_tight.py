"""Render the UPSC digest in a tighter 'dense' variant.

Differences vs. .upsc_work/render_styles.py::style_dense:
  - Margins squeezed further (L/R = 1.3 cm, T = 1.6 cm, B = 1.1 cm)
  - BODY_W recomputed so content actually fills the page width
  - Custom body_page() so the running header and page number sit close to the
    paper edge (the original positions were calibrated for 2.4 cm margins and
    end up looking marooned with tight margins)
  - Page number on outer edge (left on even pages, right on odd pages) so the
    centre-bottom isn't carrying a small italic dash

Source: .upsc_work/sample_digest_v2.md (full content -- Prelims / Mains / PYQ
blocks kept separate, Editorial deep-dive intact).

Run from project root:
    python .upsc_work/render_dense_tight.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.build_illustrated_book as B
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.units import cm

SRC = ROOT / ".upsc_work" / "sample_digest_v2.md"
OUT = ROOT / ".upsc_work" / "sample_digest_dense_tight.pdf"


def _rebuild_styles() -> None:
    ss = B.ss
    body_size, body_lead = 9.5, 13.5
    h1_size, h2_size, h3_size = 20, 12.5, 10.5
    B.H_TITLE = ParagraphStyle("HTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                               fontSize=28, leading=34, alignment=TA_CENTER,
                               textColor=B.INK, spaceAfter=14)
    B.H_SUBTITLE = ParagraphStyle("HSubtitle", parent=ss["Title"], fontName="Helvetica-Oblique",
                                  fontSize=15, leading=20, alignment=TA_CENTER,
                                  textColor=B.ACCENT, spaceAfter=8)
    B.H_META = ParagraphStyle("HMeta", parent=ss["Normal"], fontName="Helvetica",
                              fontSize=11, leading=15, alignment=TA_CENTER,
                              textColor=B.MUTED)
    B.H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                          fontSize=h1_size, leading=h1_size * 1.25,
                          textColor=B.INK, spaceBefore=4, spaceAfter=14,
                          keepWithNext=1)
    B.H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                          fontSize=h2_size, leading=h2_size * 1.33,
                          textColor=B.ACCENT,
                          spaceBefore=12, spaceAfter=5, keepWithNext=1)
    B.H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                          fontSize=h3_size, leading=h3_size * 1.33,
                          textColor=B.INK, spaceBefore=9, spaceAfter=3,
                          keepWithNext=1)
    B.BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                            fontSize=body_size, leading=body_lead,
                            textColor=B.INK, alignment=TA_JUSTIFY,
                            spaceAfter=6, allowOrphans=0, allowWidows=0)
    B.CAPTION = ParagraphStyle("Caption", parent=B.BODY, fontName="Helvetica-Oblique",
                               fontSize=8, leading=10,
                               textColor=B.MUTED, alignment=TA_CENTER,
                               spaceBefore=3, spaceAfter=8)
    B.CHAP_LABEL = ParagraphStyle("ChapLabel", parent=ss["Normal"],
                                  fontName="Helvetica-Bold", fontSize=10, leading=12,
                                  textColor=B.HIGHLIGHT, spaceAfter=4)
    B.CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName="Helvetica-Bold",
                                fontSize=8.5, leading=11,
                                textColor=colors.white, spaceAfter=4,
                                alignment=TA_LEFT)
    B.CO_BODY = ParagraphStyle("CoBody", parent=B.BODY,
                               fontSize=9, leading=12,
                               spaceAfter=3, alignment=TA_LEFT)
    B.ACCENT_HEX = "#" + B.ACCENT.hexval()[2:]
    B.HIGHLIGHT_HEX = "#" + B.HIGHLIGHT.hexval()[2:]


def _tight_body_page(canv, doc):
    """Header + footer scaled so they hug the page edge with 1.1 cm bottom
    margin. Page number alternates left/right (outer edge)."""
    canv.saveState()
    page_w, page_h = B.PAGE_W, B.PAGE_H
    margin_l, margin_r = B.MARGIN_L, B.MARGIN_R
    # --- top --------------------------------------------------------------
    canv.setStrokeColor(B.RULE)
    canv.setLineWidth(0.4)
    rule_y_top = page_h - 0.95 * cm
    canv.line(margin_l, rule_y_top, page_w - margin_r, rule_y_top)
    canv.setFillColor(B.ACCENT)
    canv.setFont("Helvetica-Bold", 8.5)
    canv.drawString(margin_l, page_h - 0.65 * cm, B.RUNNING_HEADER)
    canv.setFillColor(B.MUTED)
    canv.setFont("Helvetica", 8.5)
    canv.drawRightString(page_w - margin_r, page_h - 0.65 * cm, B.RUNNING_RIGHT)
    # --- bottom -----------------------------------------------------------
    rule_y_bot = 0.85 * cm
    canv.setStrokeColor(B.RULE)
    canv.line(margin_l, rule_y_bot, page_w - margin_r, rule_y_bot)
    canv.setFillColor(B.MUTED)
    canv.setFont("Helvetica-Oblique", 8.5)
    n = doc.page - 1
    label = f"{n}"
    text_y = 0.45 * cm
    # Outer edge: right on odd-numbered pages, left on even — like a book
    if n % 2 == 1:
        canv.drawRightString(page_w - margin_r, text_y, label)
    else:
        canv.drawString(margin_l, text_y, label)
    canv.restoreState()


def apply_dense_tight() -> None:
    # Palette ------------------------------------------------------------
    B.INK = colors.HexColor("#161B26")
    B.ACCENT = colors.HexColor("#2C5282")
    B.HIGHLIGHT = colors.HexColor("#B45309")
    B.MUTED = colors.HexColor("#4A5260")
    B.RULE = colors.HexColor("#C5CAD2")
    # Margins ------------------------------------------------------------
    B.MARGIN_L = 1.3 * cm
    B.MARGIN_R = 1.3 * cm
    B.MARGIN_T = 1.6 * cm
    B.MARGIN_B = 1.1 * cm
    B.BODY_W = B.PAGE_W - B.MARGIN_L - B.MARGIN_R
    # Callouts re-coloured to match navy accent
    B.CALLOUTS["def"]["bar"] = B.ACCENT
    B.CALLOUTS["revise"]["bar"] = B.ACCENT
    # Swap in the tighter footer/header
    B.body_page = _tight_body_page
    _rebuild_styles()


def main() -> None:
    apply_dense_tight()
    B.RUNNING_HEADER = "UPSC DAILY DIGEST"
    B.RUNNING_RIGHT = "1 Jun 2026"
    B.COVER_TAGLINE = [
        "15 exam-relevant stories from 22 pages.",
        "Paper-wise tags, static linkage, PYQs + Mains questions per article.",
    ]
    B.COVER_FOOTER = "Curated for UPSC Civil Services aspirants - cheetsheet.tech"
    B.build(
        src=SRC, out=OUT, title="UPSC Daily Digest (Dense)",
        subtitle="Indian Express - Delhi - 1 June 2026",
        features=["summary", "tldr", "qna", "chapters"],
        source_url="https://cheetsheet.tech",
    )
    import os, fitz
    size = os.path.getsize(OUT)
    pages = len(fitz.open(OUT))
    print(f"-> {OUT.name}: {pages} pages, {size/1024:.1f} KB")


if __name__ == "__main__":
    main()
