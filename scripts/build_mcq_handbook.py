#!/usr/bin/env python3
"""Render a structured Solved MCQ & PYQ Handbook PDF from Markdown.

Features:
- Professional Executive Concept & Formula Summary at top.
- Quick Answer Key Matrix table.
- Formatted Question Cards with distinct Question headers, Option lists, and emerald-green Answer Callout boxes.
- Option-by-Option Elimination Analysis.
- Exam Trap & Tip callouts.
- Automatic LaTeX/chemistry ASCII sanitization for ReportLab XML parser safety.
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Table, TableStyle, KeepTogether, Image, Preformatted,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAGE_W, PAGE_H = A4
MARGIN_L = 1.5 * cm
MARGIN_R = 1.5 * cm
MARGIN_T = 1.4 * cm
MARGIN_B = 1.35 * cm
BODY_W = PAGE_W - MARGIN_L - MARGIN_R

INK = colors.HexColor("#1A1F36")
ACCENT = colors.HexColor("#1E3A8A")       # Deep Academic Navy
ACCENT_LIGHT = colors.HexColor("#EFF6FF")
CORRECT_GREEN = colors.HexColor("#15803D") # Emerald Green for correct answer
CORRECT_BG = colors.HexColor("#F0FDF4")
HIGHLIGHT = colors.HexColor("#D97706")
MUTED = colors.HexColor("#4B5563")
RULE = colors.HexColor("#E5E7EB")

CALLOUTS = {
    "correct": {"label": "CORRECT ANSWER", "bar": CORRECT_GREEN, "tint": CORRECT_BG},
    "def":     {"label": "DEF",  "bar": colors.HexColor("#2563EB"), "tint": colors.HexColor("#EFF6FF")},
    "example": {"label": "EX",   "bar": colors.HexColor("#0D9488"), "tint": colors.HexColor("#F0FDFA")},
    "tip":     {"label": "EXAM TIP / MNEMONIC", "bar": colors.HexColor("#D97706"), "tint": colors.HexColor("#FFFBEB")},
    "warning": {"label": "EXAM TRAP / PITFALL", "bar": colors.HexColor("#DC2626"), "tint": colors.HexColor("#FEF2F2")},
    "note":    {"label": "NOTE", "bar": colors.HexColor("#4B5563"), "tint": colors.HexColor("#F3F4F6")},
    "revise":  {"label": "QUICK REVISION", "bar": colors.HexColor("#1E3A8A"), "tint": colors.HexColor("#F8FAFC")},
}

ss = getSampleStyleSheet()

DOC_TITLE = ParagraphStyle("DocTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                           fontSize=16.5, leading=20, alignment=TA_LEFT,
                           textColor=ACCENT, spaceAfter=3, keepWithNext=1)
DOC_SUB = ParagraphStyle("DocSub", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=10, leading=13, textColor=MUTED, spaceAfter=8)

H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=12.5, leading=15.5, textColor=ACCENT,
                    spaceBefore=12, spaceAfter=4, keepWithNext=1)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=11.2, leading=14.5, textColor=INK,
                    spaceBefore=10, spaceAfter=4, keepWithNext=1)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                    fontSize=10, leading=13, textColor=MUTED,
                    spaceBefore=6, spaceAfter=2, keepWithNext=1)

BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                      fontSize=9.5, leading=13.2, textColor=INK,
                      alignment=TA_LEFT, spaceAfter=3)

QUESTION_TEXT = ParagraphStyle("QuestionText", parent=BODY, fontName="Helvetica-Bold",
                               fontSize=10, leading=13.8, textColor=INK,
                               spaceBefore=2, spaceAfter=4, keepWithNext=1)

META_TAG = ParagraphStyle("MetaTag", parent=BODY, fontName="Helvetica-Oblique",
                          fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=3, keepWithNext=1)

OPTION_STYLE = ParagraphStyle("OptionStyle", parent=BODY, fontName="Helvetica",
                              fontSize=9.3, leading=12.8, textColor=INK,
                              leftIndent=12, firstLineIndent=-12, spaceAfter=2, keepWithNext=1)

CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=8, leading=9.5, textColor=colors.white,
                          spaceAfter=0, alignment=TA_LEFT)
CO_BODY = ParagraphStyle("CoBody", parent=BODY, fontSize=9.0, leading=12.0,
                         spaceAfter=2, alignment=TA_LEFT)

ACCENT_HEX = "#" + ACCENT.hexval()[2:]


def _ascii_safe(text: str) -> str:
    """Replace non-Helvetica characters with clean ASCII equivalents."""
    replacements = {
        "\u00a0": " ", "\u202f": " ", "\u2010": "-", "\u2011": "-", "\u2012": "-",
        "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u2190": "<-", "\u2192": "->",
        "\u2194": "<->", "\u2248": "~", "\u2264": "<=", "\u2265": ">=", "\u00d7": "x",
        "\u00b0": " deg", "\u00b7": "|", "\u2022": "-", "\u25cf": "-", "\u25cb": "-", "\u25aa": "-",
        "\u2713": "[Y]", "\u2714": "[Y]", "\u2717": "[X]", "\u2718": "[X]",
        "\u20b9": "Rs. ", "\u215b": " 1/8", "\u215c": " 3/8", "\u215d": " 5/8", "\u215e": " 7/8",
        "\u2153": " 1/3", "\u2154": " 2/3", "\u2155": " 1/5", "\u2156": " 2/5",
        "\u2157": " 3/5", "\u2158": " 4/5", "\u2159": " 1/6", "\u215a": " 5/6",
        "\u00bd": " 1/2", "\u00bc": " 1/4", "\u00be": " 3/4",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r'[\u2500-\u257f]', '-', text)
    return text.encode("ascii", "replace").decode("ascii")


def sanitize_math_expressions(text: str) -> str:
    r"""Convert raw LaTeX math expressions ($\text{}, \xrightarrow) into clean readable text."""
    text = re.sub(r'\\xrightarrow(?:\[.*?\])?\{(.*?)\}', r' --[\1]--> ', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\mathbf\{([^}]+)\}', r'<b>\1</b>', text)
    text = re.sub(r'\\mathit\{([^}]+)\}', r'<i>\1</i>', text)
    text = re.sub(r'\$([^$]+)\$', r'\1', text)
    text = text.replace('\\rightarrow', '->').replace('\\to', '->').replace('\\pm', '+/-')
    return text


def inline(text: str) -> str:
    """Escape XML and apply formatting for ReportLab Paragraphs."""
    text = _ascii_safe(text)
    text = sanitize_math_expressions(text)

    # XML escape
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Code tags `code`
    text = re.sub(
        r"`([^`]+)`",
        r'<font name="Courier" size="8.5" color="#1E3A8A">\1</font>',
        text,
    )

    # Bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)

    # Italic *text*
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)

    # Unescape allowed ReportLab tags
    text = re.sub(r"&lt;(/?)b&gt;", r"<\1b>", text)
    text = re.sub(r"&lt;(/?)i&gt;", r"<\1i>", text)
    text = re.sub(r"&lt;(/?)font(.*?)&gt;", r"<\1font\2>", text)
    return text


def parse_blocks(md: str) -> list[tuple[str, any]]:
    """Parse Markdown into typed structural blocks."""
    lines = md.splitlines()
    blocks = []
    i = 0
    N = len(lines)

    while i < N:
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(\*{3,}|-{3,}|_{3,})$", s):
            blocks.append(("hr", None))
            i += 1
            continue

        # Headings
        if s.startswith("# ") and not s.startswith("## "):
            blocks.append(("h1", s[2:].strip()))
            i += 1
            continue
        if s.startswith("## "):
            blocks.append(("h2", s[3:].strip()))
            i += 1
            continue
        if s.startswith("### "):
            blocks.append(("h3", s[4:].strip()))
            i += 1
            continue

        # Callout block
        m_co = re.match(r"^>\s*\[!([a-zA-Z0-9_-]+)\]\s*(.*)$", s)
        if m_co:
            kind = m_co.group(1).lower()
            title = m_co.group(2).strip()
            body_lines = []
            i += 1
            while i < N and lines[i].strip().startswith(">"):
                raw_c = lines[i].strip()
                body_lines.append(re.sub(r"^>\s?", "", raw_c))
                i += 1
            blocks.append(("callout", (kind, title, body_lines)))
            continue

        # Generic blockquote / metadata line
        if s.startswith(">"):
            b_lines = []
            while i < N and lines[i].strip().startswith(">"):
                b_lines.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            blocks.append(("quote", "\n".join(b_lines)))
            continue

        # Markdown Table
        if s.startswith("|") and i + 1 < N and re.match(r"^\s*\|?\s*:?-{3,}", lines[i+1]):
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < N and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip("|").split("|")]
                if len(row) < len(header):
                    row += [""] * (len(header) - len(row))
                rows.append(row[:len(header)])
                i += 1
            blocks.append(("table", (header, rows)))
            continue

        # Unordered list
        if s.startswith("- ") or s.startswith("* "):
            items = []
            while i < N and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(("ul", items))
            continue

        # Ordered list
        if re.match(r"^\d+\.\s", s):
            items = []
            while i < N and re.match(r"^\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s*", "", lines[i].strip()))
                i += 1
            blocks.append(("ol", items))
            continue

        # Regular Paragraph
        p_lines = [s]
        i += 1
        while i < N:
            nxt = lines[i].strip()
            if not nxt or nxt.startswith("#") or nxt.startswith(">") or nxt.startswith("|") or nxt.startswith("- ") or nxt.startswith("* ") or re.match(r"^\d+\.\s", nxt) or re.match(r"^(\*{3,}|-{3,})$", nxt):
                break
            p_lines.append(nxt)
            i += 1
        blocks.append(("p", " ".join(p_lines)))

    return blocks


def make_callout(kind: str, title: str, body_lines: list[str]) -> list:
    spec = CALLOUTS.get(kind, CALLOUTS["note"])
    label = spec["label"]
    if title:
        clean_title = re.sub(r"[*_`]", "", title).strip()
        if kind == "correct":
            clean_title = re.sub(r"^(?:correct\s*answer\s*:\s*)", "", clean_title, flags=re.IGNORECASE)
            label = f"CORRECT ANSWER: {clean_title}" if clean_title else "CORRECT ANSWER"
        else:
            label = f"{label} - {clean_title}"

    body_paras = []
    pseudo = "\n".join(body_lines)
    for k2, p2 in parse_blocks(pseudo):
        if k2 == "p":
            body_paras.append(Paragraph(inline(p2), CO_BODY))
        elif k2 == "ul":
            for it in p2:
                body_paras.append(Paragraph(
                    f'<font color="{ACCENT_HEX}"><b>-</b></font> {inline(it)}',
                    ParagraphStyle("co_li", parent=CO_BODY, leftIndent=10, firstLineIndent=-10, spaceAfter=1.5)))
        elif k2 == "ol":
            for n, it in enumerate(p2, 1):
                body_paras.append(Paragraph(
                    f'<b>{n}.</b> {inline(it)}',
                    ParagraphStyle("co_oi", parent=CO_BODY, leftIndent=12, firstLineIndent=-10, spaceAfter=1.5)))

    inner = Table([[Paragraph(inline(label), CO_LABEL)]] + [[p] for p in body_paras],
                  colWidths=[BODY_W - 0.3 * cm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), spec["bar"]),
        ("BACKGROUND", (0, 1), (-1, -1), spec["tint"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.white),
    ]))
    outer = Table([[inner]], colWidths=[BODY_W])
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBEFORE", (0, 0), (0, 0), 3, spec["bar"]),
    ]))
    return [Spacer(1, 2), KeepTogether(outer), Spacer(1, 4)]


def make_table(header: list[str], rows: list[list[str]]) -> Table:
    th = ParagraphStyle("th", parent=BODY, fontName="Helvetica-Bold",
                        fontSize=8.8, leading=11, textColor=colors.white,
                        alignment=TA_LEFT, spaceAfter=0)
    td = ParagraphStyle("td", parent=BODY, fontName="Helvetica",
                        fontSize=8.5, leading=11, alignment=TA_LEFT, spaceAfter=0)
    data = [[Paragraph(inline(c), th) for c in header]]
    for r in rows:
        data.append([Paragraph(inline(c), td) for c in r])
    col_w = BODY_W / max(1, len(header))
    t = Table(data, colWidths=[col_w] * len(header))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, HIGHLIGHT),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    return t


class NumberedCanvas:
    """Canvas wrapper to add running headers, footers, and dynamic page counts."""
    def __init__(self, doc_title: str):
        self.doc_title = doc_title

    def __call__(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)

        # Running header (pages > 1)
        if doc.page > 1:
            clean_hdr = re.sub(r"[*_`]", "", self.doc_title)[:75]
            canvas.drawString(MARGIN_L, PAGE_H - MARGIN_T + 6, f"Solved PYQ Handbook  |  {clean_hdr}")
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.4)
            canvas.line(MARGIN_L, PAGE_H - MARGIN_T + 2, PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 2)

        # Footer
        footer_text = "Cheatsheet AI  *  Competitive Exam Solved PYQ Bank"
        canvas.drawString(MARGIN_L, MARGIN_B - 12, footer_text)
        canvas.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 12, f"Page {doc.page}")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN_L, MARGIN_B - 4, PAGE_W - MARGIN_R, MARGIN_B - 4)

        canvas.restoreState()


def build(src_path: Path, out_path: Path, title: str | None = None) -> int:
    """Render markdown into an MCQ handbook PDF. Returns page count."""
    md = Path(src_path).read_text(encoding="utf-8", errors="replace")
    blocks = parse_blocks(md)

    doc = BaseDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
    )

    frame = Frame(
        MARGIN_L,
        MARGIN_B,
        BODY_W,
        PAGE_H - MARGIN_T - MARGIN_B,
        id="main_frame",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )

    doc_title = title or "Solved MCQ Handbook"
    for k, p in blocks:
        if k == "h1":
            doc_title = p
            break

    template = PageTemplate(id="mcq_template", frames=frame, onPage=NumberedCanvas(doc_title))
    doc.addPageTemplates([template])

    story = []
    i = 0
    N = len(blocks)

    while i < N:
        k, payload = blocks[i]

        if k == "h1":
            story.append(Paragraph(inline(payload), DOC_TITLE))
            story.append(Spacer(1, 2))
            i += 1
        elif k == "h2" and payload.lower().startswith("question"):
            # Collect complete Question core: Heading + Metadata + Problem + Options + Correct Answer
            q_flowables = [
                Spacer(1, 6),
                Paragraph(f'<font color="{ACCENT_HEX}"><b>{inline(payload)}</b></font>', H2),
            ]
            i += 1
            while i < N:
                k2, p2 = blocks[i]
                if k2 == "h3" or k2 == "hr" or (k2 == "h2"):
                    break
                elif k2 == "quote":
                    q_flowables.append(Paragraph(inline(p2), META_TAG))
                elif k2 == "p":
                    q_flowables.append(Paragraph(inline(p2), QUESTION_TEXT if (p2.startswith("**Q.**") or p2.startswith("Q.")) else BODY))
                elif k2 == "ol":
                    for idx, it in enumerate(p2, 1):
                        q_flowables.append(Paragraph(
                            f'<b><font color="{ACCENT_HEX}">{idx}.</font></b> {inline(it)}',
                            ParagraphStyle("ol_i", parent=BODY, leftIndent=12, firstLineIndent=-10, spaceAfter=2, keepWithNext=1)
                        ))
                elif k2 == "ul":
                    for it in p2:
                        if re.match(r"^\*\*\([A-D]\)\*\*", it) or re.match(r"^\([A-D]\)", it):
                            q_flowables.append(Paragraph(inline(it), OPTION_STYLE))
                        else:
                            q_flowables.append(Paragraph(f'<font color="{ACCENT_HEX}"><b>-</b></font> {inline(it)}',
                                                   ParagraphStyle("ul_i", parent=BODY, leftIndent=10, firstLineIndent=-8, spaceAfter=2)))
                elif k2 == "callout":
                    kind, co_title, body_lines = p2
                    q_flowables.extend(make_callout(kind, co_title, body_lines))
                i += 1
            story.append(KeepTogether(q_flowables))
        elif k == "h2":
            story.append(Paragraph(inline(payload), H1))
            i += 1
        elif k == "h3":
            story.append(Paragraph(inline(payload), H3))
            i += 1
        elif k == "quote":
            story.append(Paragraph(inline(payload), META_TAG))
            i += 1
        elif k == "p":
            if payload.startswith("**Q.**") or payload.startswith("Q."):
                story.append(Paragraph(inline(payload), QUESTION_TEXT))
            else:
                story.append(Paragraph(inline(payload), BODY))
            i += 1
        elif k == "ul":
            for it in payload:
                if re.match(r"^\*\*\([A-D]\)\*\*", it) or re.match(r"^\([A-D]\)", it):
                    story.append(Paragraph(inline(it), OPTION_STYLE))
                else:
                    story.append(Paragraph(f'<font color="{ACCENT_HEX}"><b>-</b></font> {inline(it)}',
                                           ParagraphStyle("ul_i", parent=BODY, leftIndent=10, firstLineIndent=-8, spaceAfter=2)))
            i += 1
        elif k == "ol":
            for idx, it in enumerate(payload, 1):
                story.append(Paragraph(f'<b><font color="{ACCENT_HEX}">{idx}.</font></b> {inline(it)}',
                                       ParagraphStyle("ol_i", parent=BODY, leftIndent=12, firstLineIndent=-10, spaceAfter=2)))
            i += 1
        elif k == "callout":
            kind, co_title, body_lines = payload
            story.extend(make_callout(kind, co_title, body_lines))
            i += 1
        elif k == "table":
            hdr, rows = payload
            story.append(make_table(hdr, rows))
            story.append(Spacer(1, 6))
            i += 1
        elif k == "hr":
            story.append(Spacer(1, 4))
            line_table = Table([[""]], colWidths=[BODY_W], rowHeights=[0.5])
            line_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
            story.append(line_table)
            story.append(Spacer(1, 4))
            i += 1
        else:
            i += 1

    doc.build(story)

    try:
        import pypdf
        reader = pypdf.PdfReader(str(out_path))
        return len(reader.pages)
    except Exception:
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/build_mcq_handbook.py <input.md> <output.pdf> [title]")
        sys.exit(1)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    t = sys.argv[3] if len(sys.argv) > 3 else None
    pages = build(src, out, t)
    print(f"Compiled {pages} page MCQ handbook to {out}")
