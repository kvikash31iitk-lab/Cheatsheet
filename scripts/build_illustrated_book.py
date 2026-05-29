"""Render an illustrated markdown book to a print-ready PDF, student-notes style.

This is a v2 of the original build_book_pdf.py with three changes that matter:

1. **Image support.** Markdown ``![caption](path)`` blocks render as inline
   ``Image`` flowables, auto-fit to the body frame width with the alt text
   shown as an italic caption underneath.

2. **Callout boxes.** GitHub-flavoured alert syntax becomes color-coded boxes:
       > [!def] Term
       > Definition body...
   Supported kinds: def, example, tip, warning, revise, note. Each renders as
   a left-bordered tinted box with a small label header.

3. **Lighter, airier layout.** Larger body type, more leading, more space
   around figures, and a cleaner cover. Designed to feel like dense student
   notes you would actually want to revise from.

Usage:
    Edit SRC and OUT below, then:
        python build_illustrated_book.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    NextPageTemplate, Table, TableStyle, KeepTogether, Image,
)
from PIL import Image as PILImage

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
# CONFIGURATION
# ============================================================================
SRC = Path(r"C:\Users\HP\Documents\Claude\Video notes\output\book.md")
OUT = Path(r"C:\Users\HP\Documents\Claude\Video notes\output\book.pdf")
TITLE = "From Zero to Your First Agentic AI Workflow"
SUBTITLE = "Student Notes on Building with Claude Code"
RUNNING_HEADER = "AGENTIC AI WORKFLOWS WITH CLAUDE CODE"
RUNNING_RIGHT = "Student Notes"
COVER_FOOTER = "Companion notes - based on a 26-minute walkthrough"
COVER_TAGLINE = [
    "A visual, revise-friendly companion to a hands-on tutorial",
    "on building agentic workflows with Claude Code.",
]
# Resolve image paths in markdown relative to this directory:
IMAGE_BASE = Path(r"C:\Users\HP\Documents\Claude\Video notes\work\v1")
# ============================================================================

PAGE_W, PAGE_H = A4
MARGIN_L = 2.2 * cm
MARGIN_R = 2.2 * cm
MARGIN_T = 2.4 * cm
MARGIN_B = 2.4 * cm
BODY_W = PAGE_W - MARGIN_L - MARGIN_R

# Palette — softer, more notebook-feeling than the navy/gold trading deck
INK = colors.HexColor("#1A1F36")
ACCENT = colors.HexColor("#3A6EA5")          # heading blue
HIGHLIGHT = colors.HexColor("#D97706")       # bold keyword orange
MUTED = colors.HexColor("#5A6172")
RULE = colors.HexColor("#D5DAE0")
PAGE_TINT = colors.HexColor("#FAFAF7")

# Callout palette — left bar + light tint
CALLOUTS = {
    "def":     {"label": "DEFINITION", "bar": colors.HexColor("#3A6EA5"), "tint": colors.HexColor("#EAF1F8")},
    "example": {"label": "EXAMPLE",    "bar": colors.HexColor("#2E7D52"), "tint": colors.HexColor("#E8F2EC")},
    "tip":     {"label": "PRO TIP",    "bar": colors.HexColor("#D97706"), "tint": colors.HexColor("#FBF1E1")},
    "warning": {"label": "WATCH OUT",  "bar": colors.HexColor("#B23A48"), "tint": colors.HexColor("#F8E7E9")},
    "note":    {"label": "NOTE",       "bar": colors.HexColor("#5A6172"), "tint": colors.HexColor("#F0F0EE")},
    "revise":  {"label": "REVISE IN 60 SECONDS", "bar": colors.HexColor("#3A6EA5"), "tint": colors.HexColor("#F4F1E6")},
}


# --- styles -----------------------------------------------------------------

ss = getSampleStyleSheet()

H_TITLE = ParagraphStyle("HTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                         fontSize=32, leading=38, alignment=TA_CENTER,
                         textColor=INK, spaceAfter=14)
H_SUBTITLE = ParagraphStyle("HSubtitle", parent=ss["Title"], fontName="Helvetica-Oblique",
                            fontSize=15, leading=20, alignment=TA_CENTER,
                            textColor=ACCENT, spaceAfter=8)
H_META = ParagraphStyle("HMeta", parent=ss["Normal"], fontName="Helvetica",
                        fontSize=11, leading=15, alignment=TA_CENTER, textColor=MUTED)

H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=24, leading=30, textColor=INK,
                    spaceBefore=4, spaceAfter=14, keepWithNext=1)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=15, leading=20, textColor=ACCENT,
                    spaceBefore=14, spaceAfter=6, keepWithNext=1)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                    fontSize=12, leading=16, textColor=INK,
                    spaceBefore=10, spaceAfter=4, keepWithNext=1)

BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                      fontSize=11, leading=16.5, textColor=INK,
                      alignment=TA_JUSTIFY, spaceAfter=8,
                      allowOrphans=0, allowWidows=0)
CAPTION = ParagraphStyle("Caption", parent=BODY, fontName="Helvetica-Oblique",
                         fontSize=9.5, leading=12, textColor=MUTED,
                         alignment=TA_CENTER, spaceBefore=4, spaceAfter=10)
CHAP_LABEL = ParagraphStyle("ChapLabel", parent=ss["Normal"],
                            fontName="Helvetica-Bold", fontSize=10, leading=12,
                            textColor=HIGHLIGHT, spaceAfter=4)

CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=8.5, leading=11, textColor=colors.white,
                          spaceAfter=4, alignment=TA_LEFT)
CO_BODY = ParagraphStyle("CoBody", parent=BODY, fontSize=10.5, leading=15,
                         spaceAfter=4, alignment=TA_LEFT)


# --- inline formatting ------------------------------------------------------

ACCENT_HEX = "#" + ACCENT.hexval()[2:]
HIGHLIGHT_HEX = "#" + HIGHLIGHT.hexval()[2:]


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*",
                  rf'<font color="{HIGHLIGHT_HEX}"><b>\1</b></font>', text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`",
                  r'<font face="Courier" size="9.5" color="#3A6EA5">\1</font>', text)
    return text


# --- markdown block parser -------------------------------------------------

CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\](.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")


def parse_blocks(md: str):
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1; continue

        if re.match(r"^---+$", stripped):
            yield ("hr", None); i += 1; continue

        m = IMAGE_RE.match(stripped)
        if m:
            yield ("image", (m.group(1).strip(), m.group(2).strip()))
            i += 1; continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            yield (f"h{len(m.group(1))}", m.group(2).strip()); i += 1; continue

        # Callout block: > [!kind] title-or-firstline, then continuation > lines
        m = CALLOUT_RE.match(stripped)
        if m:
            kind = m.group(1).lower()
            title = m.group(2).strip()
            buf_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            yield ("callout", (kind, title, buf_lines))
            continue

        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            yield ("quote", " ".join(b for b in buf if b)); continue

        if "|" in stripped and i + 1 < len(lines) and re.match(r"^[\s\|:\-]+$", lines[i+1].strip()) and "|" in lines[i+1]:
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            yield ("table", (header, rows)); continue

        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip())); i += 1
            yield ("ol", items); continue

        if stripped.startswith(("- ", "* ", "+ ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ", "+ ")):
                items.append(lines[i].strip()[2:].strip()); i += 1
            yield ("ul", items); continue

        # Paragraph
        buf = [stripped]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>|\||---+$|!\[)", lines[i].strip()
        ):
            buf.append(lines[i].strip()); i += 1
        yield ("p", " ".join(buf))


# --- flowable factories -----------------------------------------------------

def make_image_flowable(alt: str, path: str) -> list:
    """Render a markdown image with auto-fit width and italic caption.

    Path resolution is forgiving on purpose: the BOOK_SYSTEM prompt asks the
    LLM to write `frames/<name>.jpg`, but in practice the LLM sometimes
    drops the `frames/` prefix and writes the bare filename, and the caller
    may pass IMAGE_BASE as either the slot dir or the frames dir itself.
    We try a handful of candidates so a markdown/image_base combo that
    "looks right" still embeds the frame instead of falling to a placeholder.
    """
    p = Path(path)
    if p.is_absolute() and p.exists():
        chosen = p
    else:
        rel = Path(path)
        bare = rel.name  # "frame_00-00-00.jpg" regardless of how it was written
        candidates = [
            IMAGE_BASE / rel,                # IMAGE_BASE=slot/, path="frames/X.jpg" → slot/frames/X.jpg
            IMAGE_BASE / bare,               # IMAGE_BASE=slot/frames/, path="frames/X.jpg" → slot/frames/X.jpg
            IMAGE_BASE / "frames" / bare,    # IMAGE_BASE=slot/, path="X.jpg" → slot/frames/X.jpg
        ]
        chosen = next((c for c in candidates if c.exists()), None)
    if chosen is None or not chosen.exists():
        return [Paragraph(f"<i>[missing image: {path}]</i>", BODY)]
    p = chosen.resolve()
    try:
        with PILImage.open(p) as im:
            iw, ih = im.size
    except Exception as exc:
        return [Paragraph(f"<i>[image error: {exc}]</i>", BODY)]
    max_w = BODY_W
    max_h = (PAGE_H - MARGIN_T - MARGIN_B) * 0.55  # never bigger than ~55% of body height
    scale = min(max_w / iw, max_h / ih, 1.0)
    w, h = iw * scale, ih * scale
    img = Image(str(p), width=w, height=h)
    img.hAlign = "CENTER"
    flowables = [Spacer(1, 4), img]
    if alt:
        flowables.append(Paragraph(inline(alt), CAPTION))
    else:
        flowables.append(Spacer(1, 6))
    return [KeepTogether(flowables)]


def make_callout(kind: str, title: str, body_lines: list[str]) -> list:
    spec = CALLOUTS.get(kind, CALLOUTS["note"])
    label = spec["label"]
    if title:
        label = f"{label} - {title}"

    body_paras = []
    # Re-parse body_lines as mini-blocks: paragraphs separated by blank lines, plus list items
    pseudo = "\n".join(body_lines)
    for kind2, payload2 in parse_blocks(pseudo):
        if kind2 == "p":
            body_paras.append(Paragraph(inline(payload2), CO_BODY))
        elif kind2 == "ul":
            for it in payload2:
                body_paras.append(Paragraph(
                    f'<font color="{ACCENT_HEX}"><b>&#9642;</b></font>&nbsp;&nbsp;{inline(it)}',
                    ParagraphStyle("co_li", parent=CO_BODY, leftIndent=14,
                                   firstLineIndent=-12, spaceAfter=2)))
        elif kind2 == "ol":
            for n, it in enumerate(payload2, 1):
                body_paras.append(Paragraph(
                    f'<b>{n}.</b>&nbsp;&nbsp;{inline(it)}',
                    ParagraphStyle("co_oi", parent=CO_BODY, leftIndent=18,
                                   firstLineIndent=-14, spaceAfter=2)))

    label_para = Paragraph(label, ParagraphStyle("CoLabelInner", parent=CO_LABEL,
                                                 textColor=colors.white))

    inner = Table(
        [[label_para]] + [[p] for p in body_paras],
        colWidths=[BODY_W - 0.4 * cm],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), spec["bar"]),
        ("BACKGROUND", (0, 1), (-1, -1), spec["tint"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("LINEBEFORE", (0, 0), (0, -1), 0, spec["bar"]),
    ]))
    # Wrap in another table to get the strong left bar across the whole stack.
    outer = Table([[inner]], colWidths=[BODY_W])
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBEFORE", (0, 0), (0, 0), 3, spec["bar"]),
    ]))
    return [Spacer(1, 4), KeepTogether(outer), Spacer(1, 6)]


def make_table(header, rows):
    th = ParagraphStyle("th", parent=BODY, fontName="Helvetica-Bold",
                        fontSize=10, leading=12, textColor=colors.white,
                        alignment=TA_LEFT, spaceAfter=0)
    td = ParagraphStyle("td", parent=BODY, fontName="Helvetica",
                        fontSize=9.5, leading=12, alignment=TA_LEFT, spaceAfter=0)
    data = [[Paragraph(inline(c), th) for c in header]]
    for r in rows:
        data.append([Paragraph(inline(c), td) for c in r])
    col_w = BODY_W / len(header)
    t = Table(data, colWidths=[col_w] * len(header))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, HIGHLIGHT),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
    ]))
    return t


def make_ul(items):
    bullet_style = ParagraphStyle("BulletPara", parent=BODY, leading=15,
                                  alignment=TA_LEFT, spaceAfter=4,
                                  leftIndent=18, firstLineIndent=-12)
    out = []
    for it in items:
        out.append(Paragraph(
            f'<font color="{ACCENT_HEX}"><b>&#9642;</b></font>&nbsp;&nbsp;{inline(it)}',
            bullet_style))
    return out


def make_ol(items):
    num_style = ParagraphStyle("NumPara", parent=BODY, leading=15,
                               alignment=TA_LEFT, spaceAfter=4,
                               leftIndent=22, firstLineIndent=-18)
    out = []
    for n, it in enumerate(items, 1):
        out.append(Paragraph(
            f'<b><font color="{ACCENT_HEX}">{n}.</font></b>&nbsp;&nbsp;{inline(it)}',
            num_style))
    return out


# --- page templates ---------------------------------------------------------

def cover_page(canv, doc):
    canv.saveState()
    canv.setFillColor(PAGE_TINT)
    canv.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canv.setFillColor(ACCENT)
    canv.rect(0, PAGE_H - 1.5 * cm, PAGE_W, 0.18 * cm, fill=1, stroke=0)
    canv.setFillColor(HIGHLIGHT)
    canv.rect(0, 1.5 * cm, PAGE_W, 0.18 * cm, fill=1, stroke=0)
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica-Oblique", 9)
    canv.drawCentredString(PAGE_W / 2, 0.9 * cm, COVER_FOOTER)
    canv.restoreState()


def body_page(canv, doc):
    canv.saveState()
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.4)
    canv.line(MARGIN_L, PAGE_H - 1.6 * cm, PAGE_W - MARGIN_R, PAGE_H - 1.6 * cm)
    canv.setFillColor(ACCENT)
    canv.setFont("Helvetica-Bold", 8.5)
    canv.drawString(MARGIN_L, PAGE_H - 1.3 * cm, RUNNING_HEADER)
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica", 8.5)
    canv.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 1.3 * cm, RUNNING_RIGHT)
    canv.line(MARGIN_L, 1.7 * cm, PAGE_W - MARGIN_R, 1.7 * cm)
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica-Oblique", 8.5)
    canv.drawCentredString(PAGE_W / 2, 1.1 * cm, f"- {doc.page - 1} -")
    canv.restoreState()


# --- render ----------------------------------------------------------------

def render_block(kind, payload, story):
    if kind == "h1":
        story.append(PageBreak())
        story.append(Paragraph(inline(payload), H1))
        return
    if kind == "h2":
        m = re.match(r"^Chapter\s+(\d+)\s*[-:.—]\s*(.+)$", payload, re.IGNORECASE)
        # Only insert a PageBreak if the previous flowable isn't already one —
        # otherwise the cover's NextPageTemplate+PageBreak doubles up here.
        if not (story and isinstance(story[-1], PageBreak)):
            story.append(PageBreak())
        if m:
            story.append(Paragraph(f"CHAPTER {m.group(1)}", CHAP_LABEL))
            story.append(Paragraph(inline(m.group(2)), H1))
        else:
            story.append(Paragraph(inline(payload), H1))
        return
    if kind == "h3":
        story.append(Paragraph(inline(payload), H2)); return
    if kind in ("h4", "h5", "h6"):
        story.append(Paragraph(inline(payload), H3)); return
    if kind == "p":
        story.append(Paragraph(inline(payload), BODY)); return
    if kind == "ul":
        story.extend(make_ul(payload)); return
    if kind == "ol":
        story.extend(make_ol(payload)); return
    if kind == "image":
        story.extend(make_image_flowable(*payload)); return
    if kind == "callout":
        story.extend(make_callout(*payload)); return
    if kind == "quote":
        q = ParagraphStyle("q", parent=BODY, fontName="Helvetica-Oblique",
                           textColor=ACCENT, leftIndent=18, rightIndent=18,
                           spaceBefore=6, spaceAfter=10)
        story.append(Paragraph(inline(payload), q)); return
    if kind == "table":
        story.append(Spacer(1, 0.2 * cm))
        story.append(make_table(*payload))
        story.append(Spacer(1, 0.3 * cm)); return
    if kind == "hr":
        return  # PageBreaks handle visual separation


def render_cover_page(story, title, subtitle):
    story.append(Spacer(1, 5.5 * cm))
    story.append(Paragraph(title, H_TITLE))
    story.append(Paragraph(subtitle, H_SUBTITLE))
    story.append(Spacer(1, 1.5 * cm))
    for line in COVER_TAGLINE:
        story.append(Paragraph(line, H_META))
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())


def render(md: str):
    story: list = []
    render_cover_page(story, TITLE, SUBTITLE)

    blocks = list(parse_blocks(md))
    n, idx = len(blocks), 0
    while idx < n:
        kind, payload = blocks[idx]
        # Skip the first H1 if it duplicates the cover title — we already drew it.
        if kind == "h1" and idx == 0 and payload.lower().startswith(TITLE.lower()[:20]):
            idx += 1; continue
        render_block(kind, payload, story)
        idx += 1
    return story


def build(src: Path | None = None, out: Path | None = None,
          title: str | None = None, image_base: Path | None = None,
          subtitle: str | None = None) -> Path:
    """Render the illustrated book. Override SRC/OUT/TITLE/IMAGE_BASE per call."""
    global IMAGE_BASE, TITLE, SUBTITLE
    src = Path(src) if src else SRC
    out = Path(out) if out else OUT
    if title:
        TITLE = title
    if subtitle:
        SUBTITLE = subtitle
    if image_base:
        IMAGE_BASE = Path(image_base)

    md = src.read_text(encoding="utf-8")
    story = render(md)

    doc = BaseDocTemplate(
        str(out), pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T, bottomMargin=MARGIN_B,
        title=TITLE, author="Generated student notes",
    )
    frame_cover = Frame(0, 0, PAGE_W, PAGE_H, id="cover", showBoundary=0,
                        leftPadding=2*cm, rightPadding=2*cm,
                        topPadding=2*cm, bottomPadding=2*cm)
    frame_body = Frame(MARGIN_L, MARGIN_B, BODY_W,
                       PAGE_H - MARGIN_T - MARGIN_B, id="body", showBoundary=0)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=cover_page),
        PageTemplate(id="body",  frames=[frame_body],  onPage=body_page),
    ])
    doc.build(story)
    print(f"OK: {out}  ({out.stat().st_size/1024:.1f} kB)")
    return out


if __name__ == "__main__":
    build()
