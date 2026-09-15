"""
Builder for Structured Notes - Style 1: Executive Study Cards
"""

import html
import io
import os
import pathlib
import re
import sys
from pathlib import Path

try:
    from scripts.math_typography import sanitize_math_typography
except ImportError:
    from math_typography import sanitize_math_typography

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

PAGE_W, PAGE_H = A4
MARGIN = 1.3 * cm
BODY_W = PAGE_W - 2 * MARGIN

NAVY = colors.HexColor("#1E3A8A")        # Deep Sapphire Header
SLATE_DARK = colors.HexColor("#0F172A")  # Slate 900
SLATE_TEXT = colors.HexColor("#1E293B")  # Slate 800 for high readability
BORDER_COLOR = colors.HexColor("#CBD5E1") # Slate 300
BG_LIGHT = colors.HexColor("#F8FAFC")    # Slate 50
BG_FORMULA = colors.HexColor("#F1F5F9")  # Slate 100
AMBER = colors.HexColor("#D97706")       # Amber 600
EMERALD = colors.HexColor("#059669")     # Emerald 600
RED = colors.HexColor("#DC2626")         # Red 600

ss = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle(
    "DocTitle",
    parent=ss["Title"],
    fontName="Helvetica-Bold",
    fontSize=15.0,
    leading=18.5,
    textColor=NAVY,
    alignment=TA_LEFT,
    spaceAfter=3,
    keepWithNext=1,
)

STYLE_SUBTITLE = ParagraphStyle(
    "DocSubtitle",
    parent=ss["Normal"],
    fontName="Helvetica-Oblique",
    fontSize=9.0,
    leading=12.0,
    textColor=colors.HexColor("#64748B"),
    spaceAfter=6,
)

STYLE_H1 = ParagraphStyle(
    "H1",
    parent=ss["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=11.2,
    leading=14.0,
    textColor=colors.white,
    spaceBefore=0,
    spaceAfter=0,
    keepWithNext=1,
)

STYLE_H2 = ParagraphStyle(
    "H2",
    parent=ss["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=10.0,
    leading=13.0,
    textColor=NAVY,
    spaceBefore=7,
    spaceAfter=3,
    keepWithNext=1,
)

STYLE_BODY = ParagraphStyle(
    "Body",
    parent=ss["BodyText"],
    fontName="Helvetica",
    fontSize=8.8,
    leading=12.0,
    textColor=SLATE_TEXT,
    alignment=TA_JUSTIFY,
    spaceAfter=2.5,
)

STYLE_BULLET = ParagraphStyle(
    "Bullet",
    parent=STYLE_BODY,
    leftIndent=11,
    firstLineIndent=-8,
    spaceAfter=2.0,
)

STYLE_FORMULA = ParagraphStyle(
    "Formula",
    parent=ss["Normal"],
    fontName="Helvetica",
    fontSize=8.8,
    leading=12.0,
    textColor=SLATE_DARK,
    alignment=TA_LEFT,
)


def clean_latex_math(text: str) -> str:
    """Turn raw LaTeX equations into clean readable arithmetic expressions."""
    return sanitize_math_typography(text)


def clean_inline(text: str) -> str:
    """Format markdown bold, italics, numbers, and badges into ReportLab HTML tags."""
    if not text:
        return ""
    
    text = clean_latex_math(text)

    # XML Escape before adding HTML font tags
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def bold_repl(m):
        val = m.group(1).strip()
        # Ratios / Norms (e.g. 2:1, 1:1)
        if re.search(r"\b(\d+\s*:\s*\d+)\b", val):
            return f'<font color="#D97706"><b>{val}</b></font>'
        # Percentages / Numbers
        if re.search(r"(\d+%|\d+\s*Years?|\d+\s*Months?|\d+\s*Times?|Rs\.\s*\d+)", val, re.I):
            return f'<font color="#D97706"><b>{val}</b></font>'
        # Prohibitions / Traps
        if re.search(r"(invalid|trap|risk|prohibit|loss|defect|incorrect)", val, re.I):
            return f'<font color="#DC2626"><b>{val}</b></font>'
        # Valid / Benchmark / Positive
        if re.search(r"(valid|ideal|positive|correct|benchmark|norm|safety)", val, re.I):
            return f'<font color="#059669"><b>{val}</b></font>'
        return f'<font color="#1E3A8A"><b>{val}</b></font>'

    text = re.sub(r"\*\*(.+?)\*\*", bold_repl, text)
    text = re.sub(r"\*([^*\n]+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier-Bold" color="#1E3A8A" size="8.5">\1</font>', text)

    # Restore allowed ReportLab tags
    text = text.replace("&amp;rarr;", "&rarr;").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")
    text = text.replace("&lt;sup&gt;", "<sup>").replace("&lt;/sup&gt;", "</sup>")
    text = re.sub(r"&lt;font(.*?)&gt;", r"<font\1>", text)
    text = text.replace("&lt;/font&gt;", "</font>")
    return text


def make_h1_ribbon(title: str) -> Table:
    """A full-width shaded ribbon banner for main section headings."""
    clean_t = clean_inline(title)
    p = Paragraph(f"<b>{clean_t.upper()}</b>", STYLE_H1)
    t = Table([[p]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, NAVY),
    ]))
    return t


def make_formula_card(formula_text: str, norm_text: str = "", unit_badge: str = "") -> Table:
    """A shaded, highlighted card displaying an accounting formula and its standard benchmark."""
    clean_f = clean_inline(formula_text)
    fp = Paragraph(f'<font color="#1E3A8A"><b>FORMULA:</b></font> <font face="Courier-Bold" color="#0F172A"><b>{clean_f}</b></font>', STYLE_FORMULA)
    
    right_cells = []
    if norm_text:
        right_cells.append(f'<font color="#D97706"><b>NORM: {clean_inline(norm_text)}</b></font>')
    if unit_badge:
        right_cells.append(f'<font color="#059669"><b>[{unit_badge}]</b></font>')
        
    row_data = []
    if right_cells:
        rp = Paragraph(" | ".join(right_cells), ParagraphStyle("RightBadge", parent=STYLE_FORMULA, alignment=TA_RIGHT, fontSize=8.2))
        row_data = [[fp, rp]]
        col_w = [BODY_W * 0.65, BODY_W * 0.35]
    else:
        row_data = [[fp]]
        col_w = [BODY_W]
    
    t = Table(row_data, colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_FORMULA),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINELEFT", (0, 0), (0, -1), 3.0, NAVY),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def make_callout_box(label: str, content: str, color_hex: str = "#1E3A8A") -> Table:
    """A clean alert callout with colored left accent and label."""
    lp = Paragraph(f'<font color="{color_hex}"><b>{label}</b></font>', STYLE_FORMULA)
    cp = Paragraph(clean_inline(content), STYLE_BODY)
    t = Table([[lp], [cp]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
        ("LINELEFT", (0, 0), (0, -1), 3.0, colors.HexColor(color_hex)),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
    ]))
    return t


def build_style1_pdf(md_path: Path, pdf_path: Path, title: str = "General Accounting Principles - Ratio Analysis"):
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
    
    story.append(Paragraph(title, STYLE_TITLE))
    story.append(Paragraph("Executive Structured Study Cards | UPSC EPFO AO/EO & APFC | Instructor: Anurag Sir", STYLE_SUBTITLE))
    story.append(HRFlowable(width="100%", thickness=0.8, color=NAVY, spaceBefore=0, spaceAfter=6))
    
    lines = raw_md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
            
        if line.startswith("## "):
            sec_title = line.replace("## ", "").strip()
            story.append(Spacer(1, 5))
            story.append(make_h1_ribbon(sec_title))
            story.append(Spacer(1, 4))
            i += 1
            continue
            
        if line.startswith("### "):
            sub_title = line.replace("### ", "").strip()
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<b>{clean_inline(sub_title)}</b>", STYLE_H2))
            story.append(Spacer(1, 2))
            i += 1
            continue
            
        # Check for formula block
        if line.startswith("- **Formula:**") or line.startswith("- **Formula**:"):
            f_content = re.sub(r"^-\s*\*\*Formula:\*\*\s*", "", line, flags=re.I).strip()
            f_content = re.sub(r"^-\s*\*\*Formula\*\*:\s*", "", f_content, flags=re.I).strip()
            # If formula is on next line
            if not f_content and i + 1 < len(lines) and lines[i+1].strip().startswith("$$"):
                f_content = lines[i+1].strip()
                i += 1
            elif not f_content and i + 1 < len(lines) and not lines[i+1].strip().startswith("-"):
                f_content = lines[i+1].strip()
                i += 1
                
            norm_val = ""
            unit_val = ""
            # Check for Ideal Benchmark
            if i + 1 < len(lines) and ("Ideal Benchmark" in lines[i+1] or "Benchmark" in lines[i+1]):
                norm_val = re.sub(r"^-\s*\*\*.*?\*\*:\s*", "", lines[i+1]).strip()
                i += 1
            if "2:1" in norm_val or "2 : 1" in norm_val or "1:1" in norm_val or "1 : 1" in norm_val:
                unit_val = "PURE RATIO"
            elif "%" in f_content or "100" in f_content:
                unit_val = "PERCENTAGE (%)"
            elif "Times" in lines[i] or (i+1 < len(lines) and "Times" in lines[i+1]):
                unit_val = "TIMES"
                
            story.append(make_formula_card(f_content, norm_val, unit_val))
            story.append(Spacer(1, 3))
            i += 1
            continue
            
        if line.startswith("> [!"):
            m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", line)
            c_label = m.group(2) if m else "EXAMINATION KEY RULE"
            c_body = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                c_body.append(lines[i].strip().lstrip(">").strip())
                i += 1
            story.append(make_callout_box(c_label, " ".join(c_body), "#1E3A8A"))
            story.append(Spacer(1, 3))
            continue
            
        if "|" in line and i + 1 < len(lines) and re.match(r"^[\s\|:\-]+$", lines[i+1].strip()):
            header = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
                
            th_style = ParagraphStyle("TH", parent=STYLE_BODY, fontName="Helvetica-Bold", textColor=colors.white, fontSize=8.2, leading=11)
            td_style = ParagraphStyle("TD", parent=STYLE_BODY, fontName="Helvetica", fontSize=8.0, leading=11, textColor=SLATE_TEXT)
            
            t_data = [[Paragraph(clean_inline(c), th_style) for c in header]]
            for r in rows:
                t_data.append([Paragraph(clean_inline(c), td_style) for c in r])
                
            if len(header) == 5:
                col_w = [BODY_W * 0.22, BODY_W * 0.28, BODY_W * 0.15, BODY_W * 0.13, BODY_W * 0.22]
            elif len(header) == 3:
                col_w = [BODY_W * 0.25, BODY_W * 0.30, BODY_W * 0.45]
            else:
                col_w = [BODY_W / len(header)] * len(header)
                
            tbl = Table(t_data, colWidths=col_w, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E2E8F0")),
            ]))
            story.append(Spacer(1, 3))
            story.append(tbl)
            story.append(Spacer(1, 4))
            continue
            
        if line.startswith(("- ", "* ", "+ ")):
            b_text = re.sub(r"^[-*+]\s+", "", line)
            bullet_p = Paragraph(f'<font color="#1E3A8A"><b>&bull;</b></font> {clean_inline(b_text)}', STYLE_BULLET)
            story.append(bullet_p)
            i += 1
            continue
            
        m_num = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m_num:
            n_num = m_num.group(1)
            n_text = m_num.group(2)
            num_p = Paragraph(f'<b><font color="#1E3A8A">{n_num}.</font></b> {clean_inline(n_text)}', STYLE_BULLET)
            story.append(num_p)
            i += 1
            continue
            
        story.append(Paragraph(clean_inline(line), STYLE_BODY))
        i += 1

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 4, "UPSC EPFO APFC | GENERAL ACCOUNTING PRINCIPLES")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 4, "RATIO ANALYSIS & FINANCIAL TOOLS")
        canvas.setStrokeColor(BORDER_COLOR)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - MARGIN + 2, PAGE_W - MARGIN, PAGE_H - MARGIN + 2)
        
        canvas.drawString(MARGIN, MARGIN - 10, "Executive Study Notes — Class 27")
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 10, f"Page {doc.page}")
        canvas.line(MARGIN, MARGIN - 2, PAGE_W - MARGIN, MARGIN - 2)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    print(f"Style 1 PDF built successfully -> {pdf_path}")
