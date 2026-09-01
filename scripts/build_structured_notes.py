"""
Builder for Structured Notes (Executive Study Cards with Stacked Mathematical Fractions)
Locked standard format for Cheatsheet engine.
"""

import html
import io
import os
import pathlib
import re
import sys
from pathlib import Path

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
SLATE_TEXT = colors.HexColor("#1E293B")  # Slate 800
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
    if not text:
        return ""
    text = text.replace("$$", " ").replace("$", " ")
    text = re.sub(r"\\?text\{([^}]+)\}", r"\1", text)
    for _ in range(5):
        text = re.sub(r"\\?frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1) / (\2)", text)
    text = text.replace(r"\left(", "(").replace(r"\right)", ")")
    text = text.replace(r"\left[", "[").replace(r"\right]", "]")
    text = text.replace(r"\approx", " ≈ ").replace(r"\times", " * ").replace(r"\cdot", " * ")
    text = text.replace(r"\le", "<=").replace(r"\ge", ">=").replace(r"\pm", "+/-")
    text = text.replace("{", "").replace("}", "")
    text = text.replace("→", " &rarr; ").replace("₹", "Rs. ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_inline(text: str) -> str:
    """Format markdown bold, italics, numbers, and badges into ReportLab HTML tags."""
    if not text:
        return ""
    
    text = clean_latex_math(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def bold_repl(m):
        val = m.group(1).strip()
        # Ratios / Norms (e.g. 2:1, 1:1)
        if re.search(r"\b(\d+\s*:\s*\d+)\b", val):
            return f'<font color="#D97706"><b>{val}</b></font>'
        # Percentages / Numbers / Currency
        if re.search(r"(\d+%|\d+\s*Years?|\d+\s*Months?|\d+\s*Times?|Rs\.\s*[\d,]+(?:\.\d+)?)", val, re.I):
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

    text = text.replace("&amp;rarr;", "&rarr;").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = re.sub(r"&lt;font(.*?)&gt;", r"<font\1>", text)
    text = text.replace("&lt;/font&gt;", "</font>")
    return text


def make_h1_ribbon(title: str) -> Table:
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


def make_stacked_fraction_card(raw_formula: str, norm_text: str = "", unit_badge: str = "") -> Table:
    clean_f = clean_latex_math(raw_formula)
    clean_f = clean_f.replace("`", "")
    
    lhs = ""
    num = ""
    den = ""
    mult = ""
    
    if "=" in clean_f:
        parts = clean_f.split("=", 1)
        lhs = parts[0].strip()
        rhs = parts[1].strip()
    else:
        rhs = clean_f
        
    if "/" in rhs:
        mult_match = re.search(r"\*\s*(\d+)", rhs)
        if mult_match:
            mult = f"* {mult_match.group(1)}"
            rhs = re.sub(r"\*\s*\d+", "", rhs).strip()
            
        frac_parts = rhs.split("/", 1)
        num = frac_parts[0].strip().strip("()").strip()
        den_raw = frac_parts[1].strip()
        
        # If denominator has trailing calculation like '= 220,000/12,000 ≈ Rs. 18.33'
        if "=" in den_raw:
            d_parts = den_raw.split("=", 1)
            den = d_parts[0].strip().strip("()").strip()
            trailing_calc = f"= {d_parts[1].strip()}"
            mult = f"{mult} {trailing_calc}".strip()
        else:
            den = den_raw.strip("()").strip()
    
    style_lhs = ParagraphStyle("LHS", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=9.2, leading=11.5, textColor=NAVY, alignment=TA_LEFT)
    style_num = ParagraphStyle("NUM", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=8.8, leading=11.0, textColor=SLATE_DARK, alignment=TA_CENTER)
    style_den = ParagraphStyle("DEN", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=8.8, leading=11.0, textColor=SLATE_DARK, alignment=TA_CENTER)
    style_mult = ParagraphStyle("MULT", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=9.2, leading=11.5, textColor=NAVY, alignment=TA_LEFT)
    
    if num and den:
        p_num = Paragraph(clean_inline(num), style_num)
        p_den = Paragraph(clean_inline(den), style_den)
        
        frac_table = Table([[p_num], [p_den]])
        frac_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5),
            ("TOPPADDING", (0, 1), (-1, 1), 2.5),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 1.5),
            ("LINEABOVE", (0, 1), (-1, 1), 1.0, NAVY),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        
        row_cells = []
        if lhs:
            p_lhs = Paragraph(f"<b>{clean_inline(lhs)}</b> =", style_lhs)
            row_cells.append(p_lhs)
        row_cells.append(frac_table)
        if mult:
            p_mult = Paragraph(f"<b>{clean_inline(mult)}</b>", style_mult)
            row_cells.append(p_mult)
            
        math_expr_table = Table([row_cells])
        math_expr_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        p_lin = Paragraph(f'<font color="#1E3A8A"><b>FORMULA:</b></font> <font face="Courier-Bold" color="#0F172A"><b>{clean_inline(clean_f)}</b></font>', STYLE_FORMULA)
        math_expr_table = Table([[p_lin]])
        math_expr_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        
    right_badges = []
    if norm_text:
        right_badges.append(f'<font color="#D97706"><b>NORM: {clean_inline(norm_text)}</b></font>')
    if unit_badge:
        right_badges.append(f'<font color="#059669"><b>[{unit_badge}]</b></font>')
        
    if right_badges:
        badge_style = ParagraphStyle("BadgeR", parent=ss["Normal"], fontName="Helvetica", fontSize=8.2, leading=11, alignment=TA_RIGHT)
        p_badge = Paragraph(" | ".join(right_badges), badge_style)
        card_table = Table([[math_expr_table, p_badge]], colWidths=[BODY_W * 0.70, BODY_W * 0.30])
    else:
        card_table = Table([[math_expr_table]], colWidths=[BODY_W])
        
    card_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_FORMULA),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINELEFT", (0, 0), (0, -1), 3.0, NAVY),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return card_table


def make_callout_box(label: str, content: str, color_hex: str = "#1E3A8A") -> Table:
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


def is_formula_line(line: str) -> bool:
    """Determine if a markdown line represents an explicit formula or equation."""
    l = line.strip()
    if re.match(r"^[-*+]\s*\*\*Formula:?\*\*", l, re.I):
        return True
    if re.match(r"^\*\*Formula:?\*\*", l, re.I):
        return True
    if re.search(r"\\?frac\{", l):
        return True
    if re.match(r"^(\d+\.\s+)?(Quantity|Labor|Cost|Total Rate|Fixed Cost|Variable Cost|Overhead Rate).*?=\s*", l, re.I) and ("/" in l or "+" in l):
        return True
    return False


def build(md_path: Path, pdf_path: Path, title: str = "General Accounting Principles - Ratio Analysis"):
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
    
    story.append(Paragraph(clean_inline(title), STYLE_TITLE))
    story.append(Paragraph("Structured Study Notes & Examination Reference | UPSC EPFO AO/EO & APFC", STYLE_SUBTITLE))
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
            
        if is_formula_line(line):
            f_content = re.sub(r"^[-*+]\s*\*\*Formula:?\*\*\s*", "", line, flags=re.I).strip()
            f_content = re.sub(r"^\*\*Formula:?\*\*\s*", "", f_content, flags=re.I).strip()
            if not f_content and i + 1 < len(lines) and (lines[i+1].strip().startswith("$$") or "frac" in lines[i+1]):
                f_content = lines[i+1].strip()
                i += 1
            elif not f_content and i + 1 < len(lines) and not lines[i+1].strip().startswith("-"):
                f_content = lines[i+1].strip()
                i += 1
            elif not f_content:
                f_content = line
                
            norm_val = ""
            unit_val = ""
            if i + 1 < len(lines) and ("Ideal Benchmark" in lines[i+1] or "Benchmark" in lines[i+1]):
                norm_val = re.sub(r"^-\s*\*\*.*?\*\*:\s*", "", lines[i+1]).strip()
                i += 1
            if "2:1" in norm_val or "2 : 1" in norm_val or "1:1" in norm_val or "1 : 1" in norm_val:
                unit_val = "PURE RATIO"
            elif "%" in f_content or "100" in f_content:
                unit_val = "PERCENTAGE (%)"
            elif "Times" in lines[i] or (i+1 < len(lines) and "Times" in lines[i+1]):
                unit_val = "TIMES"
                
            story.append(make_stacked_fraction_card(f_content, norm_val, unit_val))
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
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 4, "STRUCTURED STUDY NOTES")
        canvas.setStrokeColor(BORDER_COLOR)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - MARGIN + 2, PAGE_W - MARGIN, PAGE_H - MARGIN + 2)
        
        canvas.drawString(MARGIN, MARGIN - 10, "Structured Study Notes — Executive Reference")
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 10, f"Page {doc.page}")
        canvas.line(MARGIN, MARGIN - 2, PAGE_W - MARGIN, PAGE_H - MARGIN - 2)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    print(f"OK: Structured Notes PDF -> {pdf_path}")
