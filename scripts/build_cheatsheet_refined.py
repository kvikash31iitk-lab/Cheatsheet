#!/usr/bin/env python3
"""Refined Revision Cheatsheet PDF Engine.

High-density, exhaustive revision layout ("Seedhi Baat No Bakwaas"):
- 100% Concept & Fact Retention with 0% Narrative Fluff
- Intelligent 2-Column Key-Value Grids for sub-facts & bio data
- 3-Level Hierarchical Bullets (Level 1: •, Level 2: ▪, Level 3: ▫)
- Ultra-Compact Comparative Tables (repeatRows=1)
- Exam Trap / Exception Warning Callouts
- Bullet-proof entity decoding (zero &amp; or raw entities)
- Crash-proof tag balancing & justified alignment
"""
from __future__ import annotations

import html
import io
import re
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Page Geometry
PAGE_W, PAGE_H = A4
MARGIN = 0.9 * cm
BODY_W = PAGE_W - (2 * MARGIN)

# Palette
NAVY_PRIMARY = colors.HexColor("#0F172A")    # Deep slate navy
NAVY_HEADER = colors.HexColor("#1E3A8A")     # Royal navy for banners
ACCENT_BLUE = colors.HexColor("#2563EB")     # Bright sapphire
AMBER_HIGHLIGHT = colors.HexColor("#B45309") # Rich amber for statutory numbers/limits
RED_TRAP = colors.HexColor("#B91C1C")        # Crimson for pitfalls/traps
GREEN_VALID = colors.HexColor("#15803D")     # Emerald for valid/approved conditions
TEXT_DARK = colors.HexColor("#0F172A")       # High contrast black text
TEXT_MUTED = colors.HexColor("#475569")      # Dark slate for metadata
BORDER_COLOR = colors.HexColor("#CBD5E1")    # Crisp table/callout border
BG_LIGHT = colors.HexColor("#F8FAFC")        # Soft card background

# Styles
ss = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle(
    "RefinedTitle",
    parent=ss["Title"],
    fontName="Helvetica-Bold",
    fontSize=15.5,
    leading=19.5,
    alignment=TA_LEFT,
    textColor=NAVY_PRIMARY,
    spaceAfter=2,
)

STYLE_SUBTITLE = ParagraphStyle(
    "RefinedSubtitle",
    parent=ss["Normal"],
    fontName="Helvetica",
    fontSize=8.5,
    leading=11.2,
    alignment=TA_LEFT,
    textColor=TEXT_MUTED,
    spaceAfter=3.5,
)

STYLE_H1_TEXT = ParagraphStyle(
    "RefinedH1Text",
    parent=ss["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=9.5,
    leading=12.2,
    textColor=colors.white,
    alignment=TA_LEFT,
)

STYLE_H2 = ParagraphStyle(
    "RefinedH2",
    parent=ss["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=9.2,
    leading=12.5,
    textColor=NAVY_HEADER,
    spaceBefore=3.0,
    spaceAfter=1.8,
    keepWithNext=True,
)

STYLE_H3 = ParagraphStyle(
    "RefinedH3",
    parent=ss["Heading3"],
    fontName="Helvetica-Bold",
    fontSize=8.6,
    leading=11.5,
    textColor=TEXT_DARK,
    spaceBefore=2.0,
    spaceAfter=1.2,
    keepWithNext=True,
)

STYLE_BODY = ParagraphStyle(
    "RefinedBody",
    parent=ss["BodyText"],
    fontName="Helvetica",
    fontSize=8.5,
    leading=11.8,
    alignment=TA_JUSTIFY,
    textColor=TEXT_DARK,
    spaceAfter=2.5,
    allowOrphans=0,
    allowWidows=0,
)

STYLE_BULLET_L1 = ParagraphStyle(
    "RefinedBulletL1",
    parent=STYLE_BODY,
    leftIndent=11,
    firstLineIndent=-8,
    spaceAfter=2.2,
    alignment=TA_JUSTIFY,
)

STYLE_BULLET_L2 = ParagraphStyle(
    "RefinedBulletL2",
    parent=STYLE_BODY,
    fontSize=8.3,
    leading=11.4,
    leftIndent=22,
    firstLineIndent=-8,
    spaceAfter=1.8,
    alignment=TA_JUSTIFY,
)

STYLE_BULLET_L3 = ParagraphStyle(
    "RefinedBulletL3",
    parent=STYLE_BODY,
    fontSize=8.1,
    leading=11.0,
    leftIndent=33,
    firstLineIndent=-8,
    spaceAfter=1.5,
    alignment=TA_JUSTIFY,
)

STYLE_GRID_CELL = ParagraphStyle(
    "RefinedGridCell",
    parent=STYLE_BODY,
    fontSize=8.2,
    leading=11.2,
    spaceAfter=0,
    alignment=TA_LEFT,
)

STYLE_CO_LABEL = ParagraphStyle(
    "RefinedCoLabel",
    parent=ss["Normal"],
    fontName="Helvetica-Bold",
    fontSize=7.8,
    leading=9.8,
    textColor=RED_TRAP,
    spaceAfter=1.0,
)

STYLE_CO_BODY = ParagraphStyle(
    "RefinedCoBody",
    parent=STYLE_BODY,
    fontSize=8.1,
    leading=11.2,
    spaceAfter=1.0,
    alignment=TA_JUSTIFY,
)


def _ascii_safe(text: str) -> str:
    """Sanitize text to Latin-1 range for standard Helvetica, preventing black square (■) glyph errors."""
    if not text:
        return ""
    # Strip Indic / Devanagari scripts
    text = re.sub(r"[\u0900-\u097F]+", "", text)
    replacements = {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-", "\u2012": "-",
        "\u2212": "-", "\u00ad": "-", "\u2026": "...", "\u00a0": " ",
        "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
        "₹": "Rs. ", "≈": "~", "≤": "<=", "≥": ">=", "≠": "!=",
        "•": "*", "■": "-", "▪": "-", "►": ">", "✔": "[Y]", "✖": "[X]",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)


def clean_inline(text: str) -> str:
    """Format inline markdown bold, italics, tags, and entity references safely."""
    if not text:
        return ""
    # Pre-unescape all HTML entities
    text = html.unescape(str(text))
    text = _ascii_safe(text)
    
    # LaTeX cleanup
    text = text.replace("$$", " ").replace("$", " ")
    text = re.sub(r"\\?text\{([^}]+)\}", r"\1", text)
    for _ in range(3):
        text = re.sub(r"\\?frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1) / (\2)", text)

    # Protect raw XML characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def bold_repl(m):
        inner = m.group(1).strip()
        # Clean any nested italic markdown inside bold
        inner = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", inner)
        
        # Traps / Warnings
        if re.search(r"\b(prohibit|forbidden|illegal|penalty|fine|disqualif|void|offence|breach|trap|warning|danger)\b", inner, re.I):
            return f'<font color="{RED_TRAP.hexval()}"><b>{inner}</b></font>'
        # Core sections / Articles / Acts / Ministries / Bodies / Dynasties
        elif re.search(r"\b(section|sec\.|article|art\.|act|code|ministry|commission|tribunal|committee|treaty|convention|scheme|mission|portal|index|report|dynasty|king|emperor|council)\b", inner, re.I):
            return f'<font color="{NAVY_HEADER.hexval()}"><b>{inner}</b></font>'
        # Statutory facts / Limits / Years / Numbers / Currency / Ratios
        elif re.search(r"(\b\d+[\d,\.]*\b|%|rs\.|rupees|days|months|years|hours|crores?|lakhs?|ratio|bc|ad|bce|ce)", inner, re.I):
            return f'<font color="{AMBER_HIGHLIGHT.hexval()}"><b>{inner}</b></font>'
        # Valid / Approved / Positive
        elif re.search(r"\b(valid|eligible|approved|entitled|exempt|allowed|benefit|relief)\b", inner, re.I):
            return f'<font color="{GREEN_VALID.hexval()}"><b>{inner}</b></font>'
        else:
            return f'<font color="{NAVY_HEADER.hexval()}"><b>{inner}</b></font>'

    # 1. Triple asterisks (Bold + Italic)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    # 2. Double asterisks (Bold)
    text = re.sub(r"\*\*(.+?)\*\*", bold_repl, text)
    # 3. Single asterisks (Italics)
    text = re.sub(r"(?<![\w*<])\*([^*\n<>]+?)\*(?![\w*>])", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier-Bold" color="#1E3A8A" size="7.8">\1</font>', text)

    # Restore valid formatting tags
    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;u&gt;", "<u>").replace("&lt;/u&gt;", "</u>")
    text = re.sub(r"&lt;font(.*?)&gt;", r"<font\1>", text)
    text = text.replace("&lt;/font&gt;", "</font>")
    
    # Fix any crossing tags
    text = re.sub(r"<b><i>(.*?)</b></font></i>", r"<b><i>\1</i></b></font>", text)
    text = re.sub(r"<b><i>(.*?)</b></i>", r"<b><i>\1</i></b>", text)
    text = re.sub(r"<i><b>(.*?)</i></b>", r"<i><b>\1</b></i>", text)
    return text


def make_para(text: str, style, bulletText=None) -> Paragraph:
    if not text or not str(text).strip():
        return Paragraph("", style, bulletText=bulletText)
    raw_str = str(text)
    formatted = clean_inline(raw_str)
    try:
        return Paragraph(formatted, style, bulletText=bulletText)
    except Exception:
        clean = re.sub(r"<[^>]+>", "", raw_str).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(clean, style, bulletText=bulletText)


def make_section_banner(title: str) -> Table:
    """Create a high-contrast Navy section banner with an amber accent bar."""
    p = make_para(f"<b>{title.upper()}</b>", STYLE_H1_TEXT)
    t = Table([[p]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY_HEADER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6.5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
        ("LINELEFT", (0, 0), (0, -1), 3.5, AMBER_HIGHLIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, NAVY_PRIMARY),
    ]))
    return t


def make_callout_box(label: str, content: str, kind: str = "warning") -> Table:
    """Compact callout box for exam traps and statutory exceptions."""
    accent = RED_TRAP if "trap" in label.lower() or "warning" in label.lower() else NAVY_HEADER
    lbl_p = make_para(f'<b><font color="{accent.hexval()}">{label.upper()}</font></b>', STYLE_CO_LABEL)
    body_p = make_para(content, STYLE_CO_BODY)
    t = Table([[lbl_p], [body_p]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 6.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
        ("LINELEFT", (0, 0), (0, -1), 3.0, accent),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
    ]))
    return t


def make_table(header: List[str], rows: List[List[str]]) -> Table:
    """Ultra-compact comparative table with repeatRows=1."""
    num_cols = len(header)
    th_style = ParagraphStyle("RefinedTH", parent=STYLE_BODY, fontName="Helvetica-Bold", fontSize=7.6, leading=9.8, textColor=colors.white, alignment=TA_LEFT)
    td_style = ParagraphStyle("RefinedTD", parent=STYLE_BODY, fontName="Helvetica", fontSize=7.5, leading=10.0, alignment=TA_JUSTIFY)
    
    if num_cols == 2:
        col_w = [BODY_W * 0.32, BODY_W * 0.68]
    elif num_cols == 3:
        col_w = [BODY_W * 0.28, BODY_W * 0.36, BODY_W * 0.36]
    elif num_cols == 4:
        col_w = [BODY_W * 0.22, BODY_W * 0.26, BODY_W * 0.26, BODY_W * 0.26]
    else:
        col_w = [BODY_W / num_cols] * num_cols

    data = [[make_para(c, th_style) for c in header]]
    for r in rows:
        row_cells = []
        for i, c in enumerate(r):
            p_st = ParagraphStyle("RefinedTDH", parent=td_style, fontName="Helvetica-Bold", textColor=NAVY_HEADER) if i == 0 else td_style
            row_cells.append(make_para(c, p_st))
        data.append(row_cells)

    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY_HEADER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER_COLOR),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, AMBER_HIGHLIGHT),
    ]))
    return t


def make_double_column_grid(bullet_items: List[Tuple[int, str]]) -> Table:
    """Convert a list of short key-value bullet items into a space-saving 2-column grid."""
    half_w = (BODY_W - 6) / 2
    pairs = []
    
    formatted_paras = []
    for level, text in bullet_items:
        if level == 3:
            bullet_sym = f'<font color="{TEXT_MUTED.hexval()}" size="6.5">&#9675;</font>'
            p = make_para(f"{bullet_sym}&nbsp;&nbsp;{text}", STYLE_GRID_CELL)
        elif level == 2:
            bullet_sym = f'<font color="{TEXT_MUTED.hexval()}" size="6.5">&#9642;</font>'
            p = make_para(f"{bullet_sym}&nbsp;&nbsp;{text}", STYLE_GRID_CELL)
        else:
            bullet_sym = f'<font color="{ACCENT_BLUE.hexval()}" size="7.5">&#8226;</font>'
            p = make_para(f"{bullet_sym}&nbsp;&nbsp;{text}", STYLE_GRID_CELL)
        formatted_paras.append(p)
        
    for i in range(0, len(formatted_paras), 2):
        col1 = formatted_paras[i]
        col2 = formatted_paras[i+1] if i+1 < len(formatted_paras) else Paragraph("", STYLE_GRID_CELL)
        pairs.append([col1, col2])
        
    t = Table(pairs, colWidths=[half_w, half_w])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0),
    ]))
    return t


def build(md_path: Path, pdf_path: Path, title: str = "High-Yield Revision Cheatsheet"):
    raw_md = md_path.read_text(encoding="utf-8")
    
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    
    story = []
    
    # Title & Subtitle Header
    story.append(make_para(title, STYLE_TITLE))
    story.append(make_para("High-Yield Comprehensive Revision Digest | Quick-Scan Examination Reference", STYLE_SUBTITLE))
    story.append(HRFlowable(width="100%", thickness=0.8, color=NAVY_PRIMARY, spaceBefore=0, spaceAfter=3))
    
    lines = raw_md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
            
        if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", line):
            i += 1
            continue
            
        # Top-level course title (skip if repeated)
        if line.startswith("# "):
            i += 1
            continue

        # H1 Sections (Navy Ribbon Banner)
        if line.startswith("## "):
            sec_title = line.replace("## ", "").strip()
            story.append(Spacer(1, 2.5))
            story.append(make_section_banner(sec_title))
            story.append(Spacer(1, 1.8))
            i += 1
            continue
            
        # H2 Subsections
        if line.startswith("### "):
            sub_title = line.replace("### ", "").strip()
            story.append(Spacer(1, 1.8))
            story.append(make_para(f"<b>{sub_title}</b>", STYLE_H2))
            story.append(Spacer(1, 1.0))
            i += 1
            continue
            
        # H3 Sub-subsections
        if line.startswith("#### "):
            h3_title = line.replace("#### ", "").strip()
            story.append(Spacer(1, 1.2))
            story.append(make_para(f"<b>{h3_title}</b>", STYLE_H3))
            story.append(Spacer(1, 0.8))
            i += 1
            continue
            
        # Callouts (> [!warning] or > [!def])
        if line.startswith("> [!"):
            m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", line)
            c_label = m.group(2) if m else "EXAM TRAP & KEY EXCEPTION"
            c_body = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                c_body.append(lines[i].strip().lstrip(">").strip())
                i += 1
            story.append(make_callout_box(c_label, " ".join(c_body), "warning"))
            story.append(Spacer(1, 1.8))
            continue
            
        # Tables
        if "|" in line and i + 1 < len(lines) and re.match(r"^[\s\|:\-]+$", lines[i+1].strip()):
            header = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            story.append(Spacer(1, 1.2))
            story.append(make_table(header, rows))
            story.append(Spacer(1, 2.0))
            continue
            
        # Bullets & Intelligent 2-Column Grid Detection
        if line.startswith(("- ", "* ", "+ ")):
            raw_line = lines[i]
            indent = len(raw_line) - len(raw_line.lstrip())
            
            # Check if this is a parent bullet followed by a series of sub-bullets
            b_text = re.sub(r"^[-*+]\s+", "", line)
            
            # Collect consecutive bullet block
            bullet_group = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ", "+ ")):
                curr_raw = lines[i]
                curr_indent = len(curr_raw) - len(curr_raw.lstrip())
                if curr_indent >= 4:
                    lvl = 3
                elif curr_indent >= 2:
                    lvl = 2
                else:
                    lvl = 1
                curr_text = re.sub(r"^[-*+]\s+", "", lines[i].strip())
                bullet_group.append((lvl, curr_text))
                i += 1
                
            # If the group has a parent bullet (e.g. Level 1) followed by 4+ short sub-bullets (Level >= 2 and avg len <= 65)
            # OR the whole group is 4+ short items (avg len <= 65 chars):
            sub_items = [(lvl, t) for (lvl, t) in bullet_group if lvl >= 2]
            lvl1_items = [(lvl, t) for (lvl, t) in bullet_group if lvl == 1]
            
            if len(lvl1_items) == 1 and len(sub_items) >= 4 and (sum(len(t) for _, t in sub_items) / len(sub_items) <= 65):
                # Render Level 1 parent
                p_parent = make_para(f'<font color="{ACCENT_BLUE.hexval()}" size="7.5">&#8226;</font>&nbsp;&nbsp;{lvl1_items[0][1]}', STYLE_BULLET_L1)
                story.append(p_parent)
                # Render sub-items as double-column grid!
                story.append(make_double_column_grid(sub_items))
                story.append(Spacer(1, 1.2))
            elif len(bullet_group) >= 4 and (sum(len(t) for _, t in bullet_group) / len(bullet_group) <= 60):
                # Whole group as double column
                story.append(make_double_column_grid(bullet_group))
                story.append(Spacer(1, 1.2))
            else:
                # Render individual hierarchical bullets
                for lvl, text in bullet_group:
                    if lvl == 3:
                        bullet_sym = f'<font color="{TEXT_MUTED.hexval()}" size="6.5">&#9675;</font>'
                        p = make_para(f"{bullet_sym}&nbsp;&nbsp;{text}", STYLE_BULLET_L3)
                    elif lvl == 2:
                        bullet_sym = f'<font color="{TEXT_MUTED.hexval()}" size="6.5">&#9642;</font>'
                        p = make_para(f"{bullet_sym}&nbsp;&nbsp;{text}", STYLE_BULLET_L2)
                    else:
                        bullet_sym = f'<font color="{ACCENT_BLUE.hexval()}" size="7.5">&#8226;</font>'
                        p = make_para(f"{bullet_sym}&nbsp;&nbsp;{text}", STYLE_BULLET_L1)
                    story.append(p)
            continue
            
        # Numbered List
        m_num = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m_num:
            raw_line = lines[i]
            indent = len(raw_line) - len(raw_line.lstrip())
            lvl = 3 if indent >= 4 else (2 if indent >= 2 else 1)
            n_num = m_num.group(1)
            n_text = m_num.group(2)
            if lvl == 3:
                num_p = make_para(f'<b><font color="{TEXT_MUTED.hexval()}">{n_num}.</font></b>&nbsp;&nbsp;{n_text}', STYLE_BULLET_L3)
            elif lvl == 2:
                num_p = make_para(f'<b><font color="{TEXT_MUTED.hexval()}">{n_num}.</font></b>&nbsp;&nbsp;{n_text}', STYLE_BULLET_L2)
            else:
                num_p = make_para(f'<b><font color="{NAVY_HEADER.hexval()}">{n_num}.</font></b>&nbsp;&nbsp;{n_text}', STYLE_BULLET_L1)
            story.append(num_p)
            i += 1
            continue
            
        # Plain text
        story.append(make_para(line, STYLE_BODY))
        i += 1

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.2)
        canvas.setFillColor(TEXT_MUTED)
        # Top running header
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 4, "HIGH-YIELD REVISION CHEATSHEET | EXAMINATION REFERENCE")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 4, "EXAMINATION REFERENCE")
        canvas.setStrokeColor(BORDER_COLOR)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - MARGIN + 2, PAGE_W - MARGIN, PAGE_H - MARGIN + 2)
        
        # Bottom running footer
        canvas.drawString(MARGIN, MARGIN - 10, "Generated by cheetsheet.tech — High-Density Quick Revision")
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 10, f"Page {doc.page}")
        canvas.line(MARGIN, MARGIN - 2, PAGE_W - MARGIN, MARGIN - 2)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    print(f"OK: Refined Cheatsheet PDF -> {pdf_path}")
