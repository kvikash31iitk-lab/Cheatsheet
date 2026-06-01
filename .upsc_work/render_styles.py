"""Render the UPSC digest in 4 different visual styles.

Each style monkey-patches the module-level constants in
``scripts.build_illustrated_book`` and rebuilds the ``ParagraphStyle``
objects with the chosen colours/typography, then calls ``build()``.

Run from project root:

    python .upsc_work/render_styles.py

Outputs ``sample_digest_<style>.pdf`` for each of: academic, dense, coaching, magazine.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.build_illustrated_book as B
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.units import cm

SRC = ROOT / ".upsc_work" / "sample_digest_v2.md"
OUT_DIR = ROOT / ".upsc_work"

# --- baseline so we can deepcopy a clean slate each pass --------------------
ORIGINAL = {
    "INK": B.INK, "ACCENT": B.ACCENT, "HIGHLIGHT": B.HIGHLIGHT,
    "MUTED": B.MUTED, "RULE": B.RULE,
    "CALLOUTS": deepcopy(B.CALLOUTS),
    "MARGIN_L": B.MARGIN_L, "MARGIN_R": B.MARGIN_R,
    "MARGIN_T": B.MARGIN_T, "MARGIN_B": B.MARGIN_B,
    "RUNNING_HEADER": B.RUNNING_HEADER, "RUNNING_RIGHT": B.RUNNING_RIGHT,
    "COVER_TAGLINE": list(B.COVER_TAGLINE), "COVER_FOOTER": B.COVER_FOOTER,
}


def _restore() -> None:
    """Put module back to baseline before applying the next style."""
    for k, v in ORIGINAL.items():
        setattr(B, k, deepcopy(v) if isinstance(v, (list, dict)) else v)


def _rebuild_styles(*, body_size: float, body_lead: float,
                    h1_size: float, h2_size: float, h3_size: float,
                    body_font: str = "Helvetica",
                    bold_font: str = "Helvetica-Bold",
                    italic_font: str = "Helvetica-Oblique",
                    body_align: int = TA_JUSTIFY,
                    h2_color=None) -> None:
    """Rebuild the ParagraphStyle constants on the module with the chosen
    typography knobs. Called after the colour constants are already set."""
    ss = B.ss
    B.H_TITLE = ParagraphStyle("HTitle", parent=ss["Title"], fontName=bold_font,
                               fontSize=max(h1_size + 8, 26), leading=h1_size + 14,
                               alignment=TA_CENTER, textColor=B.INK, spaceAfter=14)
    B.H_SUBTITLE = ParagraphStyle("HSubtitle", parent=ss["Title"], fontName=italic_font,
                                  fontSize=15, leading=20, alignment=TA_CENTER,
                                  textColor=B.ACCENT, spaceAfter=8)
    B.H_META = ParagraphStyle("HMeta", parent=ss["Normal"], fontName=body_font,
                              fontSize=11, leading=15, alignment=TA_CENTER,
                              textColor=B.MUTED)
    B.H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName=bold_font,
                          fontSize=h1_size, leading=h1_size * 1.25,
                          textColor=B.INK, spaceBefore=4, spaceAfter=14,
                          keepWithNext=1)
    B.H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName=bold_font,
                          fontSize=h2_size, leading=h2_size * 1.33,
                          textColor=h2_color or B.ACCENT,
                          spaceBefore=14, spaceAfter=6, keepWithNext=1)
    B.H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName=bold_font,
                          fontSize=h3_size, leading=h3_size * 1.33,
                          textColor=B.INK, spaceBefore=10, spaceAfter=4,
                          keepWithNext=1)
    B.BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName=body_font,
                            fontSize=body_size, leading=body_lead,
                            textColor=B.INK, alignment=body_align,
                            spaceAfter=8, allowOrphans=0, allowWidows=0)
    B.CAPTION = ParagraphStyle("Caption", parent=B.BODY, fontName=italic_font,
                               fontSize=max(body_size - 1.5, 8),
                               leading=max(body_lead - 4, 11),
                               textColor=B.MUTED, alignment=TA_CENTER,
                               spaceBefore=4, spaceAfter=10)
    B.CHAP_LABEL = ParagraphStyle("ChapLabel", parent=ss["Normal"],
                                  fontName=bold_font, fontSize=10, leading=12,
                                  textColor=B.HIGHLIGHT, spaceAfter=4)
    B.CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName=bold_font,
                                fontSize=8.5, leading=11,
                                textColor=colors.white, spaceAfter=4,
                                alignment=TA_LEFT)
    B.CO_BODY = ParagraphStyle("CoBody", parent=B.BODY,
                               fontSize=max(body_size - 0.5, 9),
                               leading=max(body_lead - 1.5, 12),
                               spaceAfter=4, alignment=TA_LEFT)
    B.ACCENT_HEX = "#" + B.ACCENT.hexval()[2:]
    B.HIGHLIGHT_HEX = "#" + B.HIGHLIGHT.hexval()[2:]


# --- four styles -----------------------------------------------------------

def style_academic() -> None:
    """The current blue + orange academic palette (baseline)."""
    _restore()
    # No overrides — this *is* the baseline.
    _rebuild_styles(body_size=11, body_lead=16.5, h1_size=24, h2_size=15, h3_size=12)


def style_dense() -> None:
    """Smaller font, tighter leading, narrower margins. ~30% fewer pages."""
    _restore()
    B.INK = colors.HexColor("#161B26")
    B.ACCENT = colors.HexColor("#2C5282")           # deeper blue
    B.HIGHLIGHT = colors.HexColor("#B45309")        # deeper orange
    B.MUTED = colors.HexColor("#4A5260")
    B.RULE = colors.HexColor("#C5CAD2")
    B.MARGIN_L = B.MARGIN_R = 1.6 * cm
    B.MARGIN_T = B.MARGIN_B = 1.8 * cm
    # Slightly more compact callouts (re-coloured to match)
    B.CALLOUTS["def"]["bar"] = B.ACCENT
    B.CALLOUTS["revise"]["bar"] = B.ACCENT
    _rebuild_styles(body_size=9.5, body_lead=13.5, h1_size=20, h2_size=12.5, h3_size=10.5)


def style_coaching() -> None:
    """Coaching-institute hand-out feel: mostly black, deep-red highlight,
    no tints, ALL-CAPS section headers."""
    _restore()
    B.INK = colors.HexColor("#0A0A0A")
    B.ACCENT = colors.HexColor("#0A0A0A")            # black headings
    B.HIGHLIGHT = colors.HexColor("#C8102E")         # deep red for key terms
    B.MUTED = colors.HexColor("#3A3A3A")
    B.RULE = colors.HexColor("#B5B5B5")
    B.MARGIN_L = B.MARGIN_R = 2.4 * cm
    B.MARGIN_T = B.MARGIN_B = 2.6 * cm
    # Strip tints, keep just left bars. Use red for warning, navy for def,
    # black for revise — like a Drishti handout.
    palette = {
        "def":     ("#1A1F36", "#FFFFFF"),
        "example": ("#1A1F36", "#FFFFFF"),
        "tip":     ("#C8102E", "#FFFFFF"),
        "warning": ("#C8102E", "#FFFFFF"),
        "note":    ("#3A3A3A", "#FFFFFF"),
        "revise":  ("#0A0A0A", "#FFFFFF"),
        "tldr":    ("#0A0A0A", "#FFFFFF"),
        "q":       ("#C8102E", "#FFFFFF"),
    }
    for k, (bar, tint) in palette.items():
        B.CALLOUTS[k]["bar"] = colors.HexColor(bar)
        B.CALLOUTS[k]["tint"] = colors.HexColor(tint)
    # ALL-CAPS callout labels
    for k in B.CALLOUTS:
        B.CALLOUTS[k]["label"] = B.CALLOUTS[k]["label"].upper()
    _rebuild_styles(
        body_size=10.5, body_lead=15, h1_size=22, h2_size=13.5, h3_size=11,
        body_font="Times-Roman",
        bold_font="Times-Bold",
        italic_font="Times-Italic",
        h2_color=B.INK,
    )


def style_magazine() -> None:
    """Premium magazine feel: terracotta accent, bigger type, airier."""
    _restore()
    B.INK = colors.HexColor("#1A1F36")
    B.ACCENT = colors.HexColor("#C9572B")            # terracotta (cheetsheet brand)
    B.HIGHLIGHT = colors.HexColor("#5C7E9E")         # steel blue for keywords
    B.MUTED = colors.HexColor("#6A6F7B")
    B.RULE = colors.HexColor("#E5DCC9")
    B.MARGIN_L = B.MARGIN_R = 2.6 * cm
    B.MARGIN_T = B.MARGIN_B = 2.8 * cm
    palette = {
        "def":     ("#5C7E9E", "#EDF2F6"),
        "example": ("#3F7A52", "#EAF2EC"),
        "tip":     ("#C9572B", "#FBEDE2"),
        "warning": ("#A8344A", "#F8E5E7"),
        "note":    ("#6A6F7B", "#F0EBE3"),
        "revise":  ("#C9572B", "#FBEDE2"),
        "tldr":    ("#1E6E70", "#E2F0EF"),
        "q":       ("#7B4C8C", "#EFE5F2"),
    }
    for k, (bar, tint) in palette.items():
        B.CALLOUTS[k]["bar"] = colors.HexColor(bar)
        B.CALLOUTS[k]["tint"] = colors.HexColor(tint)
    _rebuild_styles(body_size=11.5, body_lead=18, h1_size=30, h2_size=17.5, h3_size=13)


# --- runner ----------------------------------------------------------------

STYLES = [
    ("academic", "UPSC Daily Digest (Academic)", style_academic),
    ("dense",    "UPSC Daily Digest (Dense)",    style_dense),
    ("coaching", "UPSC Daily Digest (Coaching)", style_coaching),
    ("magazine", "UPSC Daily Digest (Magazine)", style_magazine),
]


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for slug, title, applier in STYLES:
        print(f"\n=== Rendering style: {slug} ===")
        applier()
        # Shared cover text for all four
        B.RUNNING_HEADER = "UPSC DAILY DIGEST"
        B.RUNNING_RIGHT = "1 Jun 2026"
        B.COVER_TAGLINE = [
            "15 exam-relevant stories from 22 pages.",
            "Paper-wise tags, static linkage, PYQs + Mains questions per article.",
        ]
        B.COVER_FOOTER = "Curated for UPSC Civil Services aspirants - cheetsheet.tech"
        out_path = OUT_DIR / f"sample_digest_{slug}.pdf"
        B.build(
            src=SRC, out=out_path, title=title,
            subtitle="Indian Express - Delhi - 1 June 2026",
            features=["summary", "tldr", "qna", "chapters"],
            source_url="https://cheetsheet.tech",
        )
        import os
        size = os.path.getsize(out_path)
        import fitz
        pages = len(fitz.open(out_path))
        print(f"  -> {out_path.name}: {pages} pages, {size/1024:.1f} KB")


if __name__ == "__main__":
    main()
