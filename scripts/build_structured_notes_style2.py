"""
Builder for Structured Notes - Style 2: Architectural Reference Blueprint
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
MARGIN = 1.2 * cm
BODY_W = PAGE_W - 2 * MARGIN

PRIMARY = colors.HexColor("#0F766E")     # Deep Teal
SECONDARY = colors.HexColor("#1E293B")   # Dark Slate
BORDER = colors.HexColor("#CBD5E1")      # Slate 300
BG_PANEL = colors.HexColor("#F8FAFC")    # Slate 50
BG_FORMULA = colors.HexColor("#F0FDFA")  # Teal 50

ss = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle(
    "Title2",
    parent=ss["Title"],
    fontName="Helvetica-Bold",
    fontSize=14.5,
    leading=18.0,
    textColor=SECONDARY,
    alignment=TA_LEFT,
    spaceAfter=2,
    keepWithNext=1,
)

STYLE_SUBTITLE = ParagraphStyle(
    "Subtitle2",
    parent=ss["Normal"],
    fontName="Helvetica",
    fontSize=8.8,
    leading=11.5,
    textColor=colors.HexColor("#64748B"),
    spaceAfter=5,
)

STYLE_H1 = ParagraphStyle(
    "H1_2",
    parent=ss["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=10.5,
    leading=13.5,
    textColor=PRIMARY,
    spaceBefore=0,
    spaceAfter=0,
    keepWithNext=1,
)

STYLE_H2 = ParagraphStyle(
    "H2_2",
    parent=ss["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=9.6,
    leading=12.2,
    textColor=SECONDARY,
    spaceBefore=5,
    spaceAfter=2,
    keepWithNext=1,
)

STYLE_BODY = ParagraphStyle(
    "Body2",
    parent=ss["BodyText"],
    fontName="Helvetica",
    fontSize=8.5,
    leading=11.5,
    textColor=SECONDARY,
    alignment=TA_JUSTIFY,
    spaceAfter=2.0,
)

STYLE_BULLET = ParagraphStyle(
    "Bullet2",
    parent=STYLE_BODY,
    leftIndent=10,
    firstLineIndent=-7,
    spaceAfter=1.8,
)

STYLE_FORMULA = ParagraphStyle(
    "Formula2",
    parent=ss["Normal"],
    fontName="Helvetica",
    fontSize=8.5,
    leading=11.5,
    textColor=SECONDARY,
    alignment=TA_LEFT,
)


def clean_latex_math(text: str) -> str:
    return sanitize_math_typography(text)


def clean_inline(text: str) -> str:
    if not text:
        return ""
    text = clean_latex_math(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def bold_repl(m):
        val = m.group(1).strip()
        if re.search(r"\b(\d+\s*:\s*\d+)\b", val):
            return f'<font color="#D97706"><b>{val}</b></font>'
        if re.search(r"(\d+%|\d+\s*Years?|\d+\s*Months?|\d+\s*Times?|Rs\.\s*\d+)", val, re.I):
            return f'<font color="#D97706"><b>{val}</b></font>'
        if re.search(r"(invalid|trap|risk|prohibit|loss|defect|incorrect)", val, re.I):
            return f'<font color="#DC2626"><b>{val}</b></font>'
        if re.search(r"(valid|ideal|positive|correct|benchmark|norm|safety)", val, re.I):
            return f'<font color="#059669"><b>{val}</b></font>'
        return f'<font color="#0F766E"><b>{val}</b></font>'

    text = re.sub(r"\*\*(.+?)\*\*", bold_repl, text)
    text = re.sub(r"\*([^*\n]+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier-Bold" color="#0F766E" size="8.2">\1</font>', text)

    text = text.replace("&amp;rarr;", "&rarr;").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")
    text = text.replace("&lt;sup&gt;", "<sup>").replace("&lt;/sup&gt;", "</sup>")
    text = re.sub(r"&lt;font(.*?)&gt;", r"<font\1>", text)
    text = text.replace("&lt;/font&gt;", "</font>")
    return text


def make_h1_panel(title: str) -> Table:
    clean_t = clean_inline(title)
    p = Paragraph(f"<b>{clean_t.upper()}</b>", STYLE_H1)
    t = Table([[p]], colWidths=[BODY_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_PANEL),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINELEFT", (0, 0), (0, -1), 3.5, PRIMARY),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
    ]))
    return t


def make_formula_chip(formula_text: str, norm_text: str = "") -> Table:
    clean_f = clean_inline(formula_text)
    fp = Paragraph(f'<font color="#0F766E"><b>FORMULA:</b></font> <font face="Courier-Bold" color="#0F172A"><b>{clean_f}</b></font>', STYLE_FORMULA)
    
    cells = []
    if norm_text:
        np = Paragraph(f'<font color="#D97706"><b>NORM: {clean_inline(norm_text)}</b></font>', ParagraphStyle("N2", parent=STYLE_FORMULA, alignment=TA_RIGHT, fontSize=8.2))
        cells = [[fp, np]]
        col_w = [BODY_W * 0.68, BODY_W * 0.32]
    else:
        cells = [[fp]]
        col_w = [BODY_W]
        
    t = Table(cells, colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_FORMULA),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#99F6E4")),
        ("LINELEFT", (0, 0), (0, -1), 2.5, PRIMARY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def build_style2_pdf(md_path: Path, pdf_path: Path, title: str = "General Accounting Principles - Ratio Analysis"):
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
    story.append(Paragraph("High-Density Reference Blueprint | UPSC EPFO AO/EO & APFC | Instructor: Anurag Sir", STYLE_SUBTITLE))
    story.append(HRFlowable(width="100%", thickness=0.8, color=PRIMARY, spaceBefore=0, spaceAfter=5))
    
    lines = raw_md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
            
        if line.startswith("## "):
            sec_title = line.replace("## ", "").strip()
            story.append(Spacer(1, 4))
            story.append(make_h1_panel(sec_title))
            story.append(Spacer(1, 3))
            i += 1
            continue
            
        if line.startswith("### "):
            sub_title = line.replace("### ", "").strip()
            story.append(Spacer(1, 3))
            story.append(Paragraph(f"<b>{clean_inline(sub_title)}</b>", STYLE_H2))
            story.append(Spacer(1, 1))
            i += 1
            continue
            
        if line.startswith("- **Formula:**") or line.startswith("- **Formula**:"):
            f_content = re.sub(r"^-\s*\*\*Formula:\*\*\s*", "", line, flags=re.I).strip()
            f_content = re.sub(r"^-\s*\*\*Formula\*\*:\s*", "", f_content, flags=re.I).strip()
            if not f_content and i + 1 < len(lines) and lines[i+1].strip().startswith("$$"):
                f_content = lines[i+1].strip()
                i += 1
            elif not f_content and i + 1 < len(lines) and not lines[i+1].strip().startswith("-"):
                f_content = lines[i+1].strip()
                i += 1
                
            norm_val = ""
            if i + 1 < len(lines) and ("Ideal Benchmark" in lines[i+1] or "Benchmark" in lines[i+1]):
                norm_val = re.sub(r"^-\s*\*\*.*?\*\*:\s*", "", lines[i+1]).strip()
                i += 1
            story.append(make_formula_chip(f_content, norm_val))
            story.append(Spacer(1, 2))
            i += 1
            continue
            
        if line.startswith("> [!"):
            m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", line)
            c_label = m.group(2) if m else "CORE RULE"
            c_body = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                c_body.append(lines[i].strip().lstrip(">").strip())
                i += 1
            lp = Paragraph(f'<font color="#0F766E"><b>[RULE] {c_label}</b></font>', STYLE_FORMULA)
            cp = Paragraph(clean_inline(" ".join(c_body)), STYLE_BODY)
            t = Table([[lp], [cp]], colWidths=[BODY_W])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BG_PANEL),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LINELEFT", (0, 0), (0, -1), 2.5, PRIMARY),
                ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(t)
            story.append(Spacer(1, 2))
            continue
            
        if "|" in line and i + 1 < len(lines) and re.match(r"^[\s\|:\-]+$", lines[i+1].strip()):
            header = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
                
            th_style = ParagraphStyle("TH2", parent=STYLE_BODY, fontName="Helvetica-Bold", textColor=colors.white, fontSize=7.8, leading=10.2)
            td_style = ParagraphStyle("TD2", parent=STYLE_BODY, fontName="Helvetica", fontSize=7.5, leading=10.0, textColor=SECONDARY)
            
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
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_PANEL]),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
            ]))
            story.append(Spacer(1, 2))
            story.append(tbl)
            story.append(Spacer(1, 3))
            continue
            
        if line.startswith(("- ", "* ", "+ ")):
            b_text = re.sub(r"^[-*+]\s+", "", line)
            bullet_p = Paragraph(f'<font color="#0F766E"><b>&bull;</b></font> {clean_inline(b_text)}', STYLE_BULLET)
            story.append(bullet_p)
            i += 1
            continue
            
        m_num = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m_num:
            n_num = m_num.group(1)
            n_text = m_num.group(2)
            num_p = Paragraph(f'<b><font color="#0F766E">{n_num}.</font></b> {clean_inline(n_text)}', STYLE_BULLET)
            story.append(num_p)
            i += 1
            continue
            
        story.append(Paragraph(clean_inline(line), STYLE_BODY))
        i += 1

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.2)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 4, "UPSC EPFO APFC | GENERAL ACCOUNTING PRINCIPLES")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 4, "RATIO ANALYSIS")
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - MARGIN + 2, PAGE_W - MARGIN, PAGE_H - MARGIN + 2)
        
        canvas.drawString(MARGIN, MARGIN - 10, "Structured Reference Blueprint — Class 27")
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 10, f"Page {doc.page}")
        canvas.line(MARGIN, MARGIN - 2, PAGE_W - MARGIN, MARGIN - 2)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    print(f"Style 2 PDF built successfully -> {pdf_path}")
