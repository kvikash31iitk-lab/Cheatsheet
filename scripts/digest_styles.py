"""Reusable style appliers for the UPSC Cheetsheet PDF renderer.

Each ``apply_<name>()`` function monkey-patches the module-level constants
in :mod:`scripts.build_illustrated_book` and rebuilds the ParagraphStyle
objects so colours/typography/margins propagate into the next ``build()``
call.

The five styles roughly map to:

  - ``academic``   — soft navy + warm orange, comfortable margins (baseline)
  - ``dense``      — same palette, smaller body, narrower margins (~30% fewer pages)
  - ``dense_tight``— the locked-in production default for UPSC Cheetsheet:
                     1.3 cm L/R margins, 1.1 cm bottom, page numbers on the
                     outer edge of the page (book-style)
  - ``coaching``   — black + deep red, Times Roman serif body, ALL-CAPS labels
  - ``magazine``   — terracotta accents, airier leading, bigger headings

The admin style picker in ``/admin/upsc/[id]`` exposes all five; the
``UpscIssue.style`` column carries whichever the admin chose for that issue.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm

from scripts import build_illustrated_book as B


# --- baseline snapshot so each apply_X() starts from a clean slate ----------

_ORIGINAL: Optional[dict] = None


def _snapshot_original() -> None:
    """Captured lazily so we don't pin down values before any monkey-patching."""
    global _ORIGINAL
    if _ORIGINAL is not None:
        return
    _ORIGINAL = {
        "INK": B.INK,
        "ACCENT": B.ACCENT,
        "HIGHLIGHT": B.HIGHLIGHT,
        "MUTED": B.MUTED,
        "RULE": B.RULE,
        "CALLOUTS": deepcopy(B.CALLOUTS),
        "MARGIN_L": B.MARGIN_L,
        "MARGIN_R": B.MARGIN_R,
        "MARGIN_T": B.MARGIN_T,
        "MARGIN_B": B.MARGIN_B,
        "BODY_W": B.BODY_W,
        "RUNNING_HEADER": B.RUNNING_HEADER,
        "RUNNING_RIGHT": B.RUNNING_RIGHT,
        "COVER_TAGLINE": list(B.COVER_TAGLINE),
        "COVER_FOOTER": B.COVER_FOOTER,
        "body_page": B.body_page,
    }


def _restore() -> None:
    """Put module back to baseline before applying the next style."""
    _snapshot_original()
    assert _ORIGINAL is not None
    for k, v in _ORIGINAL.items():
        if isinstance(v, (list, dict)):
            setattr(B, k, deepcopy(v))
        else:
            setattr(B, k, v)


def _rebuild_styles(
    *,
    body_size: float,
    body_lead: float,
    h1_size: float,
    h2_size: float,
    h3_size: float,
    body_font: str = "Helvetica",
    bold_font: str = "Helvetica-Bold",
    italic_font: str = "Helvetica-Oblique",
    body_align: int = TA_JUSTIFY,
    h2_color=None,
    co_body_align: int = TA_JUSTIFY,
) -> None:
    """Rebuild every ParagraphStyle on the module after colours/margins are set.

    ParagraphStyle bakes its ``textColor`` at construction time, so we have to
    recreate them whenever the palette changes — which is the whole reason
    these appliers exist.
    """
    ss = B.ss
    B.H_TITLE = ParagraphStyle(
        "HTitle", parent=ss["Title"], fontName=bold_font,
        fontSize=max(h1_size + 8, 26), leading=h1_size + 14,
        alignment=TA_CENTER, textColor=B.INK, spaceAfter=14,
    )
    B.H_SUBTITLE = ParagraphStyle(
        "HSubtitle", parent=ss["Title"], fontName=italic_font,
        fontSize=15, leading=20, alignment=TA_CENTER,
        textColor=B.ACCENT, spaceAfter=8,
    )
    B.H_META = ParagraphStyle(
        "HMeta", parent=ss["Normal"], fontName=body_font,
        fontSize=11, leading=15, alignment=TA_CENTER, textColor=B.MUTED,
    )
    B.H1 = ParagraphStyle(
        "H1", parent=ss["Heading1"], fontName=bold_font,
        fontSize=h1_size, leading=h1_size * 1.25,
        textColor=B.INK, spaceBefore=4, spaceAfter=14, keepWithNext=1,
    )
    B.H2 = ParagraphStyle(
        "H2", parent=ss["Heading2"], fontName=bold_font,
        fontSize=h2_size, leading=h2_size * 1.33,
        textColor=h2_color or B.ACCENT,
        spaceBefore=12, spaceAfter=5, keepWithNext=1,
    )
    B.H3 = ParagraphStyle(
        "H3", parent=ss["Heading3"], fontName=bold_font,
        fontSize=h3_size, leading=h3_size * 1.33,
        textColor=B.INK, spaceBefore=9, spaceAfter=3, keepWithNext=1,
    )
    B.BODY = ParagraphStyle(
        "Body", parent=ss["BodyText"], fontName=body_font,
        fontSize=body_size, leading=body_lead,
        textColor=B.INK, alignment=body_align,
        spaceAfter=6, allowOrphans=0, allowWidows=0,
    )
    B.CAPTION = ParagraphStyle(
        "Caption", parent=B.BODY, fontName=italic_font,
        fontSize=max(body_size - 1.5, 8),
        leading=max(body_lead - 4, 11),
        textColor=B.MUTED, alignment=TA_CENTER,
        spaceBefore=3, spaceAfter=8,
    )
    B.CHAP_LABEL = ParagraphStyle(
        "ChapLabel", parent=ss["Normal"],
        fontName=bold_font, fontSize=10, leading=12,
        textColor=B.HIGHLIGHT, spaceAfter=4,
    )
    B.CO_LABEL = ParagraphStyle(
        "CoLabel", parent=ss["Normal"], fontName=bold_font,
        fontSize=8.5, leading=11,
        textColor=colors.white, spaceAfter=4, alignment=TA_LEFT,
    )
    B.CO_BODY = ParagraphStyle(
        "CoBody", parent=B.BODY,
        fontSize=max(body_size - 0.5, 9),
        leading=max(body_lead - 1.5, 12),
        spaceAfter=3, alignment=co_body_align,
    )
    B.ACCENT_HEX = "#" + B.ACCENT.hexval()[2:]
    B.HIGHLIGHT_HEX = "#" + B.HIGHLIGHT.hexval()[2:]


# --- custom body_page used by dense_tight -----------------------------------

def _tight_body_page(canv, doc):
    """Header + footer pulled in close to the paper edge; page number on the
    outer edge (right for odd pages, left for even) like a real book."""
    canv.saveState()
    page_w, page_h = B.PAGE_W, B.PAGE_H
    margin_l, margin_r = B.MARGIN_L, B.MARGIN_R
    canv.setStrokeColor(B.RULE)
    canv.setLineWidth(0.4)
    canv.line(margin_l, page_h - 0.95 * cm, page_w - margin_r, page_h - 0.95 * cm)
    canv.setFillColor(B.ACCENT)
    canv.setFont("Helvetica-Bold", 8.5)
    canv.drawString(margin_l, page_h - 0.65 * cm, B.RUNNING_HEADER)
    canv.setFillColor(B.MUTED)
    canv.setFont("Helvetica", 8.5)
    canv.drawRightString(page_w - margin_r, page_h - 0.65 * cm, B.RUNNING_RIGHT)
    canv.setStrokeColor(B.RULE)
    canv.line(margin_l, 0.85 * cm, page_w - margin_r, 0.85 * cm)
    canv.setFillColor(B.MUTED)
    canv.setFont("Helvetica-Oblique", 8.5)
    n = doc.page - 1
    if n % 2 == 1:
        canv.drawRightString(page_w - margin_r, 0.45 * cm, str(n))
    else:
        canv.drawString(margin_l, 0.45 * cm, str(n))
    canv.restoreState()


# === appliers ================================================================

def apply_academic() -> None:
    """Soft navy + warm orange. Baseline look from the original cheatsheet
    renderer; comfortable margins."""
    _restore()
    _rebuild_styles(body_size=11, body_lead=16.5, h1_size=24, h2_size=15, h3_size=12)


def apply_dense() -> None:
    """Same palette, smaller body, narrower margins. ~30% fewer pages than
    academic. Pre-cursor to dense_tight; kept for the admin picker."""
    _restore()
    B.INK = colors.HexColor("#161B26")
    B.ACCENT = colors.HexColor("#2C5282")
    B.HIGHLIGHT = colors.HexColor("#B45309")
    B.MUTED = colors.HexColor("#4A5260")
    B.RULE = colors.HexColor("#C5CAD2")
    B.MARGIN_L = B.MARGIN_R = 1.6 * cm
    B.MARGIN_T = B.MARGIN_B = 1.8 * cm
    B.BODY_W = B.PAGE_W - B.MARGIN_L - B.MARGIN_R
    B.CALLOUTS["def"]["bar"] = B.ACCENT
    B.CALLOUTS["revise"]["bar"] = B.ACCENT
    _rebuild_styles(body_size=9.5, body_lead=13.5, h1_size=20, h2_size=12.5, h3_size=10.5)


def apply_dense_tight() -> None:
    """Locked-in production default for UPSC Cheetsheet. Aggressive margins,
    outer-edge page numbers, header pulled close to the top edge."""
    _restore()
    B.INK = colors.HexColor("#161B26")
    B.ACCENT = colors.HexColor("#2C5282")
    B.HIGHLIGHT = colors.HexColor("#B45309")
    B.MUTED = colors.HexColor("#4A5260")
    B.RULE = colors.HexColor("#C5CAD2")
    B.MARGIN_L = 1.3 * cm
    B.MARGIN_R = 1.3 * cm
    B.MARGIN_T = 1.6 * cm
    B.MARGIN_B = 1.1 * cm
    B.BODY_W = B.PAGE_W - B.MARGIN_L - B.MARGIN_R
    B.CALLOUTS["def"]["bar"] = B.ACCENT
    B.CALLOUTS["revise"]["bar"] = B.ACCENT
    B.body_page = _tight_body_page
    _rebuild_styles(body_size=9.5, body_lead=13.5, h1_size=20, h2_size=12.5, h3_size=10.5)


def apply_coaching() -> None:
    """Coaching-institute hand-out feel: black headings, deep-red highlight,
    Times Roman serif body, ALL-CAPS callout labels."""
    _restore()
    B.INK = colors.HexColor("#0A0A0A")
    B.ACCENT = colors.HexColor("#0A0A0A")
    B.HIGHLIGHT = colors.HexColor("#C8102E")
    B.MUTED = colors.HexColor("#3A3A3A")
    B.RULE = colors.HexColor("#B5B5B5")
    B.MARGIN_L = B.MARGIN_R = 2.4 * cm
    B.MARGIN_T = B.MARGIN_B = 2.6 * cm
    B.BODY_W = B.PAGE_W - B.MARGIN_L - B.MARGIN_R
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
    for k in B.CALLOUTS:
        B.CALLOUTS[k]["label"] = B.CALLOUTS[k]["label"].upper()
    _rebuild_styles(
        body_size=10.5, body_lead=15,
        h1_size=22, h2_size=13.5, h3_size=11,
        body_font="Times-Roman", bold_font="Times-Bold", italic_font="Times-Italic",
        h2_color=B.INK,
    )


def apply_magazine() -> None:
    """Premium magazine feel: terracotta accent, bigger type, airier."""
    _restore()
    B.INK = colors.HexColor("#1A1F36")
    B.ACCENT = colors.HexColor("#C9572B")
    B.HIGHLIGHT = colors.HexColor("#5C7E9E")
    B.MUTED = colors.HexColor("#6A6F7B")
    B.RULE = colors.HexColor("#E5DCC9")
    B.MARGIN_L = B.MARGIN_R = 2.6 * cm
    B.MARGIN_T = B.MARGIN_B = 2.8 * cm
    B.BODY_W = B.PAGE_W - B.MARGIN_L - B.MARGIN_R
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


# Public name -> applier registry. Admin picker reads .keys(); pipeline does
# ``STYLES[issue.style]()`` before each build.
STYLES = {
    "academic":    apply_academic,
    "dense":       apply_dense,
    "dense_tight": apply_dense_tight,
    "coaching":    apply_coaching,
    "magazine":    apply_magazine,
}
