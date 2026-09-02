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

import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    NextPageTemplate, Table, TableStyle, KeepTogether, Image, HRFlowable,
)
from PIL import Image as PILImage

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
# CONFIGURATION
# ============================================================================
SRC = Path(r"C:\Users\HP\Documents\Claude\Video notes\output\book.md")
OUT = Path(r"C:\Users\HP\Documents\Claude\Video notes\output\book.pdf")
TITLE = "Academic Master Handbook"
SUBTITLE = "Comprehensive Master Lecture Handbook"
RUNNING_HEADER = "EXHAUSTIVE ACADEMIC MASTER HANDBOOK"
RUNNING_RIGHT = "Master Notes"
COVER_FOOTER = "Cheatsheet AI  *  Exhaustive Academic Master Handbook"
COVER_TAGLINE = [
    "An exhaustive, high-fidelity academic handbook covering",
    "100% of concepts, derivations, heuristics, and worked examples.",
]
# Defaults saved at import time so build() can reset after each call.
# The UPSC pipeline sets these globals before calling build(); without a
# reset they bleed into the next video-book build in the same process.
_D_RUNNING_HEADER = RUNNING_HEADER
_D_RUNNING_RIGHT = RUNNING_RIGHT
_D_COVER_FOOTER = COVER_FOOTER
_D_COVER_TAGLINE = list(COVER_TAGLINE)
# Resolve image paths in markdown relative to this directory:
IMAGE_BASE = Path(r"C:\Users\HP\Documents\Claude\Video notes\work\v1")
# ============================================================================

PAGE_W, PAGE_H = A4
MARGIN_L = 1.3 * cm
MARGIN_R = 1.3 * cm
MARGIN_T = 1.5 * cm
MARGIN_B = 1.5 * cm
BODY_W = PAGE_W - MARGIN_L - MARGIN_R

# Palette — crisp, high contrast, readable typography
INK = colors.HexColor("#000000")             # Pure deep black ink for maximum readability
ACCENT = colors.HexColor("#1D4ED8")          # Deep royal sapphire blue
HIGHLIGHT = colors.HexColor("#B45309")       # Rich amber highlight
MUTED = colors.HexColor("#1E293B")           # High-contrast dark slate gray
RULE = colors.HexColor("#CBD5E1")
PAGE_TINT = colors.HexColor("#FAFAF7")

# Multi-color highlight system
COLOR_BLUE = "#1D4ED8"     # Core concepts, statutory references
COLOR_AMBER = "#B45309"    # Key numbers, penalties, deadlines
COLOR_GREEN = "#15803D"    # Valid, approved, positive conditions
COLOR_RED = "#B91C1C"      # Prohibitions, disqualifications, violations
COLOR_PURPLE = "#6D28D9"   # Definitions, authorities, sections
COLOR_TEAL = "#0F766E"     # Case laws, landmark judgments

WHITE_BG = colors.HexColor("#FFFFFF")

# Callout palette — left bar + zero-tint clean white background
CALLOUTS = {
    "def":     {"label": "DEFINITION", "bar": colors.HexColor("#1D4ED8"), "tint": WHITE_BG},
    "example": {"label": "EXAMPLE",    "bar": colors.HexColor("#15803D"), "tint": WHITE_BG},
    "tip":     {"label": "PRO TIP",    "bar": colors.HexColor("#B45309"), "tint": WHITE_BG},
    "warning": {"label": "WATCH OUT",  "bar": colors.HexColor("#B91C1C"), "tint": WHITE_BG},
    "note":    {"label": "NOTE",       "bar": colors.HexColor("#4B5563"), "tint": WHITE_BG},
    "revise":  {"label": "REVISE IN 60 SECONDS", "bar": colors.HexColor("#0F766E"), "tint": WHITE_BG},
    "tldr":    {"label": "WHY IN NEWS", "bar": colors.HexColor("#0D7377"), "tint": WHITE_BG},
    "q":       {"label": "QUESTION",   "bar": colors.HexColor("#6D28D9"), "tint": WHITE_BG},
    "correct": {"label": "CORRECT",    "bar": colors.HexColor("#15803D"), "tint": WHITE_BG},
}


# --- styles -----------------------------------------------------------------

ss = getSampleStyleSheet()

H_TITLE = ParagraphStyle("HTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                         fontSize=28, leading=34, alignment=TA_CENTER,
                         textColor=INK, spaceAfter=10)
H_SUBTITLE = ParagraphStyle("HSubtitle", parent=ss["Title"], fontName="Helvetica-Oblique",
                            fontSize=13.5, leading=18, alignment=TA_CENTER,
                            textColor=ACCENT, spaceAfter=6)
H_META = ParagraphStyle("HMeta", parent=ss["Normal"], fontName="Helvetica",
                        fontSize=10, leading=14, alignment=TA_CENTER, textColor=MUTED)

DOC_TITLE = ParagraphStyle("DocTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                          fontSize=21, leading=26, alignment=TA_LEFT,
                          textColor=INK, spaceBefore=4, spaceAfter=8, keepWithNext=1)
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=15, leading=19, textColor=INK,
                    spaceBefore=4, spaceAfter=6, keepWithNext=1)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=13.5, leading=17, textColor=ACCENT,
                    spaceBefore=8, spaceAfter=4, keepWithNext=1)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                    fontSize=11, leading=14.5, textColor=INK,
                    spaceBefore=5, spaceAfter=2.5, keepWithNext=1)

BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                      fontSize=10.2, leading=15.2, textColor=INK,
                      alignment=TA_JUSTIFY, spaceAfter=5,
                      allowOrphans=0, allowWidows=0)
CAPTION = ParagraphStyle("Caption", parent=BODY, fontName="Helvetica-Oblique",
                         fontSize=8.5, leading=11, textColor=MUTED,
                         alignment=TA_CENTER, spaceBefore=3, spaceAfter=6)
CHAP_LABEL = ParagraphStyle("ChapLabel", parent=ss["Normal"],
                            fontName="Helvetica-Bold", fontSize=9.5, leading=11.5,
                            textColor=HIGHLIGHT, spaceAfter=3)

CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=8.5, leading=11, textColor=colors.white,
                          spaceAfter=2, alignment=TA_LEFT)
CO_BODY = ParagraphStyle("CoBody", parent=BODY, fontSize=9.5, leading=13.5,
                         spaceAfter=2.5, alignment=TA_JUSTIFY)


# --- inline formatting ------------------------------------------------------

ACCENT_HEX = "#" + ACCENT.hexval()[2:]
HIGHLIGHT_HEX = "#" + HIGHLIGHT.hexval()[2:]


def _clean_latex_math(text: str) -> str:
    r"""Convert raw LaTeX math expressions (\frac{}, \approx, \sqrt{}, \text{}, etc.) into clean typography."""
    text = _ascii_safe(text)
    text = re.sub(r'\\xrightarrow(?:\[(.*?)\])?\{(.*?)\}', r' -> [\2] -> ', text)

    for _ in range(5):
        def repl_frac(m):
            num = m.group(1).strip()
            den = m.group(2).strip()
            has_op = lambda s: any(op in s for op in ['+', '-', '*', '=', '±']) and not (s.startswith('(') and s.endswith(')'))
            num_clean = f"({num})" if has_op(num) else num
            den_clean = f"({den})" if has_op(den) else den
            return f"{num_clean} / {den_clean}"
        text = re.sub(r'\\?(?:frac|tfrac|dfrac)\{([^{}]+)\}\{([^{}]+)\}', repl_frac, text)

    text = re.sub(r'\\(?:mathrm|textbf|mathbf)\{([^}]+)\}', r'<b>\1</b>', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\(?:mathit|textit)\{([^}]+)\}', r'<i>\1</i>', text)
    text = re.sub(r'\\sqrt\{([^}]+)\}', r'√(\1)', text)
    text = re.sub(r'\\sqrt([0-9a-zA-Z])', r'√\1', text)

    symbols = {
        r'\approx': '~', r'\sim': '~', r'\neq': '!=', r'\ne': '!=',
        r'\leq': '<=', r'\le': '<=', r'\geq': '>=', r'\ge': '>=',
        r'\times': 'x', r'\div': '/', r'\pm': '+/-', r'\mp': '-/+',
        r'\cdot': '*', r'\circ': ' deg', r'\degree': ' deg', r'\infty': 'inf',
        r'\rightarrow': '->', r'\to': '->', r'\leftarrow': '<-',
        r'\Rightarrow': '=>', r'\Leftarrow': '<=', r'\Leftrightarrow': '<=>',
        r'\pi': 'pi', r'\theta': 'theta', r'\alpha': 'alpha', r'\beta': 'beta',
        r'\gamma': 'gamma', r'\Delta': 'Delta', r'\delta': 'delta', r'\lambda': 'lambda',
        r'\mu': 'mu', r'\sigma': 'sigma', r'\omega': 'omega', r'\Omega': 'Omega',
        r'\phi': 'phi', r'\rho': 'rho', r'\tau': 'tau', r'\epsilon': 'epsilon',
        r'\sum': 'SUM', r'\prod': 'PROD', r'\int': 'INT',
    }
    for k, v in symbols.items():
        text = re.sub(re.escape(k) + r'(?![a-zA-Z])', v, text)

    # 4. Superscripts and Subscripts
    text = re.sub(r'\^\{([^}]+)\}', r'<sup>\1</sup>', text)
    text = re.sub(r'_\{([^}]+)\}', r'<sub>\1</sub>', text)

    # 1. Un-nest \frac{a}{b} iteratively (up to 5 levels)
    for _ in range(5):
        def repl_frac(m):
            num = m.group(1).strip()
            den = m.group(2).strip()
            has_op = lambda s: any(op in s for op in ['+', '-', '*', '=', '±']) and not (s.startswith('(') and s.endswith(')'))
            num_clean = f"({num})" if has_op(num) else num
            den_clean = f"({den})" if has_op(den) else den
            return f"{num_clean} / {den_clean}"
        text = re.sub(r'\\?(?:frac|tfrac|dfrac)\{([^{}]+)\}\{([^{}]+)\}', repl_frac, text)

    text = re.sub(r'\$([^\$]+)\$', r'\1', text)
    text = text.replace('$', '')
    text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)
    return text


def _ascii_safe(text: str) -> str:
    # 1. Strip unmapped Devanagari / Indic Unicode scripts to prevent black square missing glyph boxes (■) in Helvetica
    text = re.sub(r'[\u0900-\u097F]+', '', text)
    # 2. Map typographic punctuation, math symbols, and unicode quotes
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
    # Strip non-printable control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    return text


def inline(text: str) -> str:
    import html
    text = html.unescape(text)  # pre-decode any existing &amp;, &lt;, &gt; to prevent double escaping
    text = _ascii_safe(text)
    text = _clean_latex_math(text)
    # Strip orphaned bold/italic markers the LLM left unclosed (e.g. lone '**')
    text = _clean_orphaned_markers(text)
    if not text.strip():
        return ''

    # Convert Unicode sub/superscripts & arrows to ReportLab tags
    sub_map = {
        '₀': '<sub>0</sub>', '₁': '<sub>1</sub>', '₂': '<sub>2</sub>', '₃': '<sub>3</sub>', '₄': '<sub>4</sub>',
        '₅': '<sub>5</sub>', '₆': '<sub>6</sub>', '₇': '<sub>7</sub>', '₈': '<sub>8</sub>', '₉': '<sub>9</sub>',
        '₊': '<sub>+</sub>', '₋': '<sub>-</sub>',
    }
    sup_map = {
        '⁰': '<sup>0</sup>', '¹': '<sup>1</sup>', '²': '<sup>2</sup>', '³': '<sup>3</sup>', '⁴': '<sup>4</sup>',
        '⁵': '<sup>5</sup>', '⁶': '<sup>6</sup>', '⁷': '<sup>7</sup>', '⁸': '<sup>8</sup>', '⁹': '<sup>9</sup>',
        '⁺': '<sup>+</sup>', '⁻': '<sup>-</sup>',
    }
    for k, v in sub_map.items():
        text = text.replace(k, v)
    for k, v in sup_map.items():
        text = text.replace(k, v)
    text = text.replace('→', '&rarr;').replace('←', '&larr;').replace('↔', '&harr;').replace('Δ', '&Delta;').replace('°', '&deg;')

    # Only escape bare ampersands that are NOT already valid HTML entities
    text = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|rarr|larr|harr|Delta|deg|nbsp|bull|#\d+);)', '&amp;', text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")

    # Multi-color tags
    text = re.sub(r"==([^=]+?)==", rf'<font color="{COLOR_AMBER}"><b>\1</b></font>', text)
    text = re.sub(r"\[red\](.*?)\[/red\]", rf'<font color="{COLOR_RED}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[green\](.*?)\[/green\]", rf'<font color="{COLOR_GREEN}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[blue\](.*?)\[/blue\]", rf'<font color="{COLOR_BLUE}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[purple\](.*?)\[/purple\]", rf'<font color="{COLOR_PURPLE}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[amber\](.*?)\[/amber\]", rf'<font color="{COLOR_AMBER}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[teal\](.*?)\[/teal\]", rf'<font color="{COLOR_TEAL}"><b>\1</b></font>', text, flags=re.IGNORECASE)

    # Triple asterisks: bold + italic in rich amber
    text = re.sub(r"\*\*\*(.+?)\*\*\*", rf'<font color="{COLOR_AMBER}"><b><i>\1</i></b></font>', text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # Semantic bold coloring
    def _bold_repl(m):
        inner = m.group(1).strip()
        if re.search(r"\b(prohibit|forbidden|illegal|penalty|fine|imprisonment|punish|disqualif|void|offence|breach|guilty|fail|trap|warning|danger)\b", inner, re.I):
            return f'<font color="{COLOR_RED}"><b>{inner}</b></font>'
        elif re.search(r"\b(section|sec\.|article|art\.|act|code|tribunal|commission|board|cbt|epfo|ilo|ministry|court|parliament|ordinance)\b", inner, re.I):
            return f'<font color="{COLOR_BLUE}"><b>{inner}</b></font>'
        elif re.search(r"\b(valid|eligible|approved|entitled|exempt|allowed|permitted|benefit|relief|right)\b", inner, re.I):
            return f'<font color="{COLOR_GREEN}"><b>{inner}</b></font>'
        elif re.search(r"(\b\d+[\d,\.]*\b|%|rs\.|rupees|days|months|years|hours|timeline|schedule|threshold|ceiling)", inner, re.I):
            return f'<font color="{COLOR_AMBER}"><b>{inner}</b></font>'
        else:
            return f'<font color="#1E3A8A"><b>{inner}</b></font>'

    text = re.sub(r"\*\*(.+?)\*\*", _bold_repl, text)
    text = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", lambda m: f'<u>{m.group(1)}</u>', text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier" size="9.5" color="#1E3A8A">\1</font>', text)

    # Automatic Statutory Fact Highlighting
    fact_re = re.compile(
        r'(?i)(?<![#\w>])'
        r'('
        r'\b\d+(?:[\.,]\d+)?\s*(?:-\s*)?'
        r'(?:days?|working\s+days?|weeks?|months?|years?|hours?|percent|%|lakhs?|crores?|rs\.?|rupees|inr)\b'
        r'|'
        r'(?:rs\.?|inr|₹)\s*\d+(?:[\.,]\d+)?'
        r')'
        r'(?![^<]*>)'
    )
    text = fact_re.sub(rf'<font color="{COLOR_AMBER}"><b>\1</b></font>', text)

    # Unescape allowed ReportLab tags and normalize anchors
    text = re.sub(r"&lt;a\s+name=['\"]?(.*?)['\"]?\s*&gt;", r'<a name="\1">', text, flags=re.IGNORECASE)
    text = re.sub(r"<a\s+name=['\"]?(.*?)['\"]?\s*>", r'<a name="\1">', text, flags=re.IGNORECASE)
    text = re.sub(r"&lt;a\s+id=['\"]?(.*?)['\"]?\s*&gt;", r'<a name="\1">', text, flags=re.IGNORECASE)
    text = re.sub(r"<a\s+id=['\"]?(.*?)['\"]?\s*>", r'<a name="\1">', text, flags=re.IGNORECASE)
    text = re.sub(r"&lt;/a&gt;", r'</a>', text, flags=re.IGNORECASE)
    text = re.sub(r"&lt;(/?)b&gt;", r"<\1b>", text)
    text = re.sub(r"&lt;(/?)i&gt;", r"<\1i>", text)
    text = re.sub(r"&lt;(/?)u&gt;", r"<\1u>", text)
    text = re.sub(r"&lt;(/?)sup&gt;", r"<\1sup>", text)
    text = re.sub(r"&lt;(/?)sub&gt;", r"<\1sub>", text)
    text = re.sub(r"&lt;(/?)font(.*?)&gt;", r"<\1font\2>", text)
    text = re.sub(r"&lt;br\s*/?&gt;", r"<br/>", text, flags=re.IGNORECASE)
    text = text.replace("&amp;rarr;", "&rarr;").replace("&amp;larr;", "&larr;").replace("&amp;harr;", "&harr;")
    text = text.replace("&amp;Delta;", "&Delta;").replace("&amp;deg;", "&deg;").replace("&amp;nbsp;", "&nbsp;").replace("&amp;bull;", "&bull;").replace("&amp;#8226;", "&#8226;").replace("&amp;#9646;", "&#9646;").replace("&amp;#9642;", "&#9642;")
    return text


def make_para(text: str, style, bulletText=None) -> Paragraph:
    """Construct a Paragraph with safe fallback if inner XML is malformed."""
    if text is None:
        return Paragraph("", style, bulletText=bulletText)
    raw_str = str(text)
    if not raw_str.strip():
        return Paragraph("", style, bulletText=bulletText)
    
    # If the text has already been formatted with ReportLab XML tags, use it directly;
    # otherwise format it through inline().
    if re.search(r"<(?:font|b|i|u|sup|sub|a|br)\b", raw_str, re.I) or "&#" in raw_str:
        formatted_str = raw_str
    else:
        formatted_str = inline(raw_str)

    try:
        return Paragraph(formatted_str, style, bulletText=bulletText)
    except Exception:
        clean = re.sub(r"<[^>]+>", "", formatted_str)
        clean = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        try:
            return Paragraph(clean, style, bulletText=bulletText)
        except Exception:
            safe_ascii = "".join(c for c in clean if ord(c) < 128)
            return Paragraph(safe_ascii, style, bulletText=bulletText)


safe_paragraph = make_para


# --- markdown block parser -------------------------------------------------

CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\](.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")


def _clean_orphaned_markers(text: str) -> str:
    """Strip dangling bold/italic markers that the LLM left unclosed.

    E.g. '**' alone, or '**word' without a closing '**'.
    We only strip if the markers are genuinely orphaned (odd count or
    the entire text is just markers + whitespace).
    """
    s = text.strip()
    # Entire text is just marker noise (e.g. '**', '***', '* *')
    if re.fullmatch(r'[\s*_`]+', s):
        return ''
    # Unclosed bold: odd number of '**' sequences
    if s.count('**') % 2 != 0:
        s = s.replace('**', '')
    # Unclosed italic: odd number of lone '*' (not part of **)
    temp = s.replace('**', '')
    if temp.count('*') % 2 != 0:
        s = re.sub(r'(?<!\*)\*(?!\*)', '', s)
    return s.strip()


def _clean_list_item(text: str) -> str:
    """Sanitize a single bullet / numbered-list item.

    Handles:
      - Double-dash bullets: '- text' from original '- - text'
      - Orphaned bold/italic markers
      - Returns empty string for junk-only items
    """
    # Collapse leading dashes:  '- - text' → 'text', '-- text' → 'text'
    text = re.sub(r'^[-*+]\s+', '', text.strip())
    text = _clean_orphaned_markers(text)
    return text.strip()


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

        # Code fence / Diagram block
        if stripped.startswith("```"):
            fence_head = stripped[3:].strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip().startswith("```"):
                i += 1
            if fence_head in ("arrangement:circular", "arrangement:linear", "diagram:triangle", "diagram:venn"):
                yield ("diagram", (fence_head, "\n".join(buf)))
            elif fence_head == "mermaid":
                yield ("mermaid", "\n".join(buf))
            else:
                yield ("code", "\n".join(buf))
            continue

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
                raw_line = lines[i]
                indent = len(raw_line) - len(raw_line.lstrip())
                level = 2 if indent >= 2 else 1
                cleaned = _clean_list_item(re.sub(r"^\d+\.\s+", "", raw_line.strip()))
                if cleaned:
                    items.append((level, cleaned))
                i += 1
            if items:
                yield ("ol", items)
            continue

        if stripped.startswith(("- ", "* ", "+ ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ", "+ ")):
                raw_line = lines[i]
                indent = len(raw_line) - len(raw_line.lstrip())
                level = 2 if indent >= 2 else 1
                cleaned = _clean_list_item(raw_line.strip()[2:].strip())
                if cleaned:
                    items.append((level, cleaned))
                i += 1
            if items:
                yield ("ul", items)
            continue

        # Paragraph
        buf = [stripped]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>|\||---+$|!\[)", lines[i].strip()
        ):
            buf.append(lines[i].strip()); i += 1
        yield ("p", " ".join(buf))


# --- flowable factories -----------------------------------------------------

def make_image_flowable(alt: str, path: str) -> list:
    """Render a markdown image with auto-fit width and italic caption."""
    p = Path(path)
    if p.is_absolute() and p.exists():
        chosen = p
    else:
        rel = Path(path)
        bare = rel.name
        candidates = [
            IMAGE_BASE / rel,
            IMAGE_BASE / bare,
            IMAGE_BASE / "frames" / bare,
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
    max_h = (PAGE_H - MARGIN_T - MARGIN_B) * 0.55
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
    if title and title.strip().lower() != label.strip().lower():
        label = f"{label} : {title}"

    body_paras = []
    pseudo = "\n".join(body_lines)
    for kind2, payload2 in parse_blocks(pseudo):
        if kind2 == "p":
            clean_p = payload2.replace(r"\text{ Crore}", " Crore").replace(r"\text{ Cr}", " Cr").replace(r"\text{", "").replace("}", "")
            body_paras.append(make_para(clean_p, ParagraphStyle("co_pg", parent=CO_BODY, fontSize=9.2, leading=14.0, spaceAfter=3.5, alignment=TA_JUSTIFY)))
        elif kind2 == "ul":
            for it_entry in payload2:
                level, it = it_entry if isinstance(it_entry, tuple) else (1, it_entry)
                clean_it = it.replace(r"\text{ Crore}", " Crore").replace(r"\text{ Cr}", " Cr").replace(r"\text{", "").replace("}", "")
                m = re.match(r"^(\s*\*\*?[^*:]+\*\*?:?)(.*)$", clean_it)
                if m:
                    styled_it = f'<b><font color="#1E3A8A">{m.group(1).strip()}</font></b>{m.group(2)}'
                else:
                    styled_it = clean_it
                indent_val = 22 if level >= 2 else 12
                bullet_sym = "&#9642;" if level >= 2 else "&#9646;"
                body_paras.append(make_para(f'<font color="{spec["bar"].hexval()}">{bullet_sym}</font>&nbsp;&nbsp;{inline(styled_it)}',
                                            ParagraphStyle(f"co_lig_{level}", parent=CO_BODY, fontSize=9.2, leading=14.0, leftIndent=indent_val, firstLineIndent=-10, spaceAfter=2.5, alignment=TA_JUSTIFY)))
        elif kind2 == "ol":
            for n, it_entry in enumerate(payload2, 1):
                level, it = it_entry if isinstance(it_entry, tuple) else (1, it_entry)
                clean_it = it.replace(r"\text{ Crore}", " Crore").replace(r"\text{ Cr}", " Cr").replace(r"\text{", "").replace("}", "")
                indent_val = 24 if level >= 2 else 14
                body_paras.append(make_para(f'<b><font color="#1E3A8A">{n}.</font></b>&nbsp;&nbsp;{inline(clean_it)}',
                                            ParagraphStyle(f"co_oig_{level}", parent=CO_BODY, fontSize=9.2, leading=14.0, leftIndent=indent_val, firstLineIndent=-12, spaceAfter=2.5, alignment=TA_JUSTIFY)))

    label_para = make_para(f'<b><font color="{spec["bar"].hexval()}">{label}</font></b>', 
                           ParagraphStyle("CoLabelGold", parent=CO_LABEL, fontSize=9.0, leading=11))

    inner = Table(
        [[label_para]] + [[p] for p in body_paras],
        colWidths=[BODY_W - 0.2 * cm],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5),
        ("TOPPADDING", (0, 1), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5.5),
        ("LINEBEFORE", (0, 0), (0, -1), 3.5, spec["bar"]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
    ]))
    return [Spacer(1, 4), KeepTogether(inner) if len(body_paras) <= 3 else inner, Spacer(1, 6)]


def make_table(header, rows):
    num_cols = len(header)
    th = ParagraphStyle("th_gold", parent=BODY, fontName="Helvetica-Bold",
                        fontSize=8.5, leading=11, textColor=colors.white,
                        alignment=TA_LEFT)
    td = ParagraphStyle("td_gold", parent=BODY, fontName="Helvetica",
                        fontSize=8.0, leading=11.2, alignment=TA_JUSTIFY)
    
    if num_cols == 2:
        col_widths = [5.5 * cm, BODY_W - 5.5 * cm]
    elif num_cols == 3:
        col_widths = [4.4 * cm, 7.0 * cm, 7.0 * cm]
    elif num_cols == 4:
        col_widths = [3.8 * cm, 4.8 * cm, 4.8 * cm, 5.0 * cm]
    elif num_cols == 5:
        col_widths = [3.2 * cm, 3.2 * cm, 4.0 * cm, 4.0 * cm, 4.0 * cm]
    else:
        col_widths = [BODY_W / num_cols] * num_cols

    data = [[make_para(c, th) for c in header]]
    for r in rows:
        row_cells = []
        for i, c in enumerate(r):
            c_clean = c.replace(r"\text{ Crore}", " Crore").replace(r"\text{ Cr}", " Cr").replace(r"\text{", "").replace("}", "")
            if i == 0:
                p_style = ParagraphStyle("td_h_gold", parent=td, fontName="Helvetica-Bold", textColor=colors.HexColor("#1E3A8A"))
            else:
                p_style = td
            row_cells.append(make_para(c_clean, p_style))
        data.append(row_cells)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#0D9488")),
    ]))
    return t


def make_ul(items):
    bullet_style_l1 = ParagraphStyle(
        "BulletGoldL1", parent=BODY, fontName="Helvetica",
        fontSize=9.6, leading=14.6, alignment=TA_JUSTIFY,
        spaceAfter=3.5, leftIndent=14, firstLineIndent=-10
    )
    bullet_style_l2 = ParagraphStyle(
        "BulletGoldL2", parent=BODY, fontName="Helvetica",
        fontSize=9.2, leading=13.8, alignment=TA_JUSTIFY,
        spaceAfter=2.5, leftIndent=26, firstLineIndent=-10
    )
    out = []
    for it_entry in items:
        level, it = it_entry if isinstance(it_entry, tuple) else (1, it_entry)
        clean_it = it.replace(r"\text{ Crore}", " Crore").replace(r"\text{ Cr}", " Cr").replace(r"\text{", "").replace("}", "")
        m = re.match(r"^(\s*\*\*?[^*:]+\*\*?:?)(.*)$", clean_it)
        if m:
            prefix = m.group(1).strip()
            rest = m.group(2)
            styled_text = f'<b><font color="#1E3A8A">{prefix}</font></b>{rest}'
        else:
            styled_text = clean_it

        if level >= 2:
            out.append(make_para(
                f'<font color="#475569" size="8">&#9646;</font>&nbsp;&nbsp;{inline(styled_text)}',
                bullet_style_l2
            ))
        else:
            out.append(make_para(
                f'<font color="#2563EB" size="10">&#8226;</font>&nbsp;&nbsp;{inline(styled_text)}',
                bullet_style_l1
            ))
    return out


def make_ol(items):
    num_style_l1 = ParagraphStyle(
        "NumGoldL1", parent=BODY, fontName="Helvetica",
        fontSize=9.6, leading=14.6, alignment=TA_JUSTIFY,
        spaceAfter=3.5, leftIndent=16, firstLineIndent=-12
    )
    num_style_l2 = ParagraphStyle(
        "NumGoldL2", parent=BODY, fontName="Helvetica",
        fontSize=9.2, leading=13.8, alignment=TA_JUSTIFY,
        spaceAfter=2.5, leftIndent=28, firstLineIndent=-12
    )
    out = []
    for n, it_entry in enumerate(items, 1):
        level, it = it_entry if isinstance(it_entry, tuple) else (1, it_entry)
        clean_it = it.replace(r"\text{ Crore}", " Crore").replace(r"\text{ Cr}", " Cr").replace(r"\text{", "").replace("}", "")
        m = re.match(r"^(\s*\*\*?[^*:]+\*\*?:?)(.*)$", clean_it)
        if m:
            prefix = m.group(1).strip()
            rest = m.group(2)
            styled_text = f'<b><font color="#1E3A8A">{prefix}</font></b>{rest}'
        else:
            styled_text = clean_it

        if level >= 2:
            out.append(make_para(
                f'<b><font color="#475569">{n}.</font></b>&nbsp;&nbsp;{inline(styled_text)}',
                num_style_l2
            ))
        else:
            out.append(make_para(
                f'<b><font color="#1E3A8A">{n}.</font></b>&nbsp;&nbsp;{inline(styled_text)}',
                num_style_l1
            ))
    return out


# === opt-in feature support ================================================
# Everything below is gated by the ``features`` list passed to ``build()``.
# When a feature flag is absent the helpers are simply not called and the
# rendered PDF matches the pre-features output byte-for-byte. See
# bot/cache.py::FEATURE_ORDER for the canonical flag list.

# Summary card: extracted from a ``<!--SUMMARY-->...<!--/SUMMARY-->`` block
# the LLM writes at the top of the markdown. We pull it out before the main
# parser runs and render it as its own page right after the cover.
SUMMARY_BLOCK_RE = re.compile(
    r"<!--\s*SUMMARY\s*-->(.*?)<!--\s*/SUMMARY\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# Mermaid code fences. We match the whole fence (incl. backticks) so the
# replacement can swap it for an `![Diagram](path)` image ref that the
# existing image flowable handles.
MERMAID_FENCE_RE = re.compile(
    r"^```mermaid\s*\n(.*?)^```\s*$",
    re.DOTALL | re.MULTILINE,
)

# Chapter titles for the index page. Matches the same shape the existing
# parser uses to detect chapters (`## Chapter N — title` / `Chapter N - title`).
CHAPTER_HEADING_RE = re.compile(
    r"^##\s+(Chapter\s+\d+\s*[-—:.]\s*.+)$",
    re.MULTILINE | re.IGNORECASE,
)


def _extract_summary_block(md: str) -> tuple[str | None, str]:
    """Pull the `<!--SUMMARY-->` block out of the markdown.

    Returns ``(summary_md, cleaned_md)``. ``summary_md`` is ``None`` if no
    block was present — in that case the caller skips rendering a summary
    page. Multiple blocks: only the first is honoured; the rest are left
    in place (will show as raw HTML comments → invisible in the PDF).
    """
    m = SUMMARY_BLOCK_RE.search(md)
    if not m:
        return None, md
    summary = m.group(1).strip()
    cleaned = md[:m.start()] + md[m.end():]
    return summary, cleaned


# Puppeteer config shipped in the repo — passes ``--no-sandbox`` so mmdc's
# bundled Chromium starts when our VPS runs the bot as root (crbug.com/638180).
# When the file is missing (older checkout / non-standard layout) we just skip
# the ``-p`` flag and let mmdc use its defaults — fine on non-root systems.
_MMDC_PUPPETEER_CONFIG = Path(__file__).resolve().parent / "mmdc-puppeteer.json"


def _render_mermaid_blocks(md: str, out_dir: Path) -> str:
    """Replace ``` ```mermaid ``` `` fences with ``![caption](path.png)`` after
    rendering each block to a PNG via the `mmdc` CLI.

    Graceful degradation:
      - If `mmdc` is not on PATH, every mermaid block is stripped (the PDF
        still builds, just without diagrams). A warning is logged.
      - If a specific block fails to render (bad syntax / Chromium crash),
        that one block is stripped; the rest still render.
    Either way, the PDF build is never killed by a diagram problem.
    """
    if not MERMAID_FENCE_RE.search(md):
        return md  # no diagrams in this document — nothing to do
    mmdc = shutil.which("mmdc")
    if not mmdc:
        print("[mermaid] WARN: `mmdc` not on PATH; stripping mermaid blocks.",
              flush=True)
        return MERMAID_FENCE_RE.sub("", md)

    out_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def _repl(m: re.Match) -> str:
        counter["n"] += 1
        idx = counter["n"]
        src = m.group(1).strip()
        if not src:
            return ""
        in_file = out_dir / f"_mermaid_{idx}.mmd"
        out_file = out_dir / f"_mermaid_{idx}.png"
        in_file.write_text(src, encoding="utf-8")
        cmd = [mmdc, "-i", str(in_file), "-o", str(out_file),
               "-b", "white", "-w", "1400", "-H", "900"]
        if _MMDC_PUPPETEER_CONFIG.exists():
            cmd.extend(["-p", str(_MMDC_PUPPETEER_CONFIG)])
        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=90, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            stderr = getattr(exc, "stderr", "") or ""
            print(f"[mermaid] block {idx} render failed; dropping. "
                  f"stderr={stderr[:200]!r}", flush=True)
            return ""
        # Pick a caption from the first non-empty line so the figure has
        # *some* labelling even though the LLM doesn't write one.
        first = next((l.strip() for l in src.splitlines() if l.strip()), "")
        if first.lower().startswith("mindmap"):
            caption = "Concept mindmap"
        elif first.lower().startswith("flowchart") or first.lower().startswith("graph"):
            caption = "Process flowchart"
        elif first.lower().startswith("sequencediagram"):
            caption = "Sequence diagram"
        else:
            caption = "Diagram"
        # IMAGE_RE expects an absolute path or a path resolvable against
        # IMAGE_BASE; absolute is unambiguous here.
        return f"\n\n![{caption}]({out_file.resolve().as_posix()})\n\n"

    return MERMAID_FENCE_RE.sub(_repl, md)


def _extract_chapter_titles(md: str) -> list[str]:
    """Return the list of chapter heading strings in document order."""
    return [m.strip() for m in CHAPTER_HEADING_RE.findall(md)]


def _make_qr_image_reader(url: str, *, box: int = 8, border: int = 2):
    """Render a QR code PNG for ``url`` and return an in-memory
    ``ImageReader`` ReportLab can draw. Returns ``None`` if the ``qrcode``
    lib isn't installed (graceful no-op so the build never breaks)."""
    try:
        import qrcode  # type: ignore
        from reportlab.lib.utils import ImageReader
    except ImportError:
        print("[qr] WARN: `qrcode` lib not installed; skipping QR code.",
              flush=True)
        return None
    qr = qrcode.QRCode(box_size=box, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1A1F36", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


# --- new flowable factories -------------------------------------------------

def make_summary_card(summary_md: str) -> list:
    """Render the extracted SUMMARY block as a styled card.

    The LLM writes free-form markdown inside the block; we re-parse it with
    the same `parse_blocks` so bullets, bold, etc. all behave naturally,
    then wrap the whole thing in a tinted Table for a "card" look.
    """
    inner_styles_body = ParagraphStyle(
        "SumBody", parent=BODY, fontSize=11.5, leading=16,
        textColor=INK, spaceAfter=4, alignment=TA_LEFT,
    )
    inner_bullet = ParagraphStyle(
        "SumBullet", parent=inner_styles_body, leftIndent=14,
        firstLineIndent=-12, spaceAfter=3,
    )
    label = Paragraph(
        "AT A GLANCE",
        ParagraphStyle("SumLabel", parent=CO_LABEL,
                       textColor=colors.white, fontSize=9, leading=12),
    )
    body_flowables: list = []
    for k, p in parse_blocks(summary_md):
        if k == "p":
            body_flowables.append(Paragraph(inline(p), inner_styles_body))
        elif k == "ul":
            for it in p:
                body_flowables.append(Paragraph(
                    f'<font color="{ACCENT_HEX}"><b>&#9642;</b></font>'
                    f'&nbsp;&nbsp;{inline(it)}', inner_bullet))
        elif k == "ol":
            for i, it in enumerate(p, 1):
                body_flowables.append(Paragraph(
                    f'<b><font color="{ACCENT_HEX}">{i}.</font></b>'
                    f'&nbsp;&nbsp;{inline(it)}', inner_bullet))
        # quotes / tables / etc. inside a summary card don't really make
        # sense; if the LLM emits one we just skip it rather than over-engineer

    rows = [[label]] + [[fl] for fl in body_flowables]
    card = Table(rows, colWidths=[BODY_W - 0.4 * cm])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    return [Spacer(1, 6), KeepTogether(card), Spacer(1, 12)]


def make_chapter_index(chapters: list[str]) -> list:
    """Render a simple chapter listing (no page numbers; ReportLab doesn't
    expose them at flow time without a TableOfContents pass and that's more
    complexity than this feature deserves)."""
    if not chapters:
        return []
    out: list = [
        PageBreak(),
        Paragraph("CONTENTS", CHAP_LABEL),
        Paragraph("Chapter Index", H1),
        Spacer(1, 8),
    ]
    item_style = ParagraphStyle(
        "ChapIdx", parent=BODY, fontSize=12, leading=18, spaceAfter=6,
        alignment=TA_LEFT, leftIndent=4,
    )
    for ch in chapters:
        out.append(Paragraph(
            f'<font color="{HIGHLIGHT_HEX}">&#9642;</font>&nbsp;&nbsp;'
            f'{inline(ch)}',
            item_style,
        ))
    return out


# --- page templates ---------------------------------------------------------

# Set by ``build()`` when the ``chapters`` feature is on AND a source_url
# was passed in. The cover_page draw callback reads these as globals because
# ReportLab's PageTemplate callback signature is fixed at (canv, doc) and
# can't accept arbitrary extras. Resetting to defaults at the top of build()
# keeps successive runs in the same Python process clean.
SHOW_QR: bool = False
SOURCE_URL: str | None = None

# Optional masthead image on the cover (replaces the big text title). Set
# from the pipeline before calling build(); ``None`` means legacy text cover.
# Path should point to a PNG at native aspect ratio — display width is fixed
# at 12 cm and height scales proportionally.
MASTHEAD_PATH: Path | None = None


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

    # Optional QR code linking back to the source video — opt-in via the
    # ``chapters`` feature. Placed in the top-right corner where it doesn't
    # fight with the centred title block below the top accent bar.
    if SHOW_QR and SOURCE_URL:
        qr = _make_qr_image_reader(SOURCE_URL)
        if qr is not None:
            size = 2.4 * cm
            x = PAGE_W - 2.2 * cm - size
            y = PAGE_H - 1.8 * cm - size - 0.4 * cm
            canv.drawImage(qr, x, y, width=size, height=size, mask="auto")
            canv.setFillColor(MUTED)
            canv.setFont("Helvetica", 7)
            canv.drawCentredString(x + size / 2, y - 0.32 * cm,
                                   "scan for the source video")
    canv.restoreState()


def body_page(canv, doc):
    canv.saveState()
    if doc.page > 1:
        canv.setStrokeColor(RULE)
        canv.setLineWidth(0.4)
        canv.line(MARGIN_L, PAGE_H - 1.4 * cm, PAGE_W - MARGIN_R, PAGE_H - 1.4 * cm)
        canv.setFillColor(ACCENT)
        canv.setFont("Helvetica-Bold", 8.0)
        canv.drawString(MARGIN_L, PAGE_H - 1.15 * cm, RUNNING_HEADER)
        canv.setFillColor(MUTED)
        canv.setFont("Helvetica", 8.0)
        canv.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 1.15 * cm, RUNNING_RIGHT)
    
    # Bottom footer line & page number
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.4)
    canv.line(MARGIN_L, 1.4 * cm, PAGE_W - MARGIN_R, 1.4 * cm)
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica", 8.0)
    canv.drawString(MARGIN_L, 0.9 * cm, "Generated by cheatsheet.tech")
    canv.drawRightString(PAGE_W - MARGIN_R, 0.9 * cm, RUNNING_RIGHT)
    canv.drawCentredString(PAGE_W / 2, 0.9 * cm, f"Page {doc.page}")
    canv.restoreState()


# --- render ----------------------------------------------------------------

def _strip_timestamps(text: str) -> str:
    """Remove timestamp ranges like [00:00 - 18:45] or (12:30) from titles."""
    text = re.sub(r'\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*-\s*\d{1,2}:\d{2}(?::\d{2})?\s*\]', '', text)
    text = re.sub(r'\(\s*\d{1,2}:\d{2}(?::\d{2})?\s*-\s*\d{1,2}:\d{2}(?::\d{2})?\s*\)', '', text)
    text = re.sub(r'\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*\]', '', text)
    text = re.sub(r'\(\s*\d{1,2}:\d{2}(?::\d{2})?\s*\)', '', text)
    return text.strip()


def render_block(kind, payload, story):
    if kind == "h1":
        cleaned_h1 = _strip_timestamps(payload)
        story.append(Spacer(1, 0.1 * cm))
        story.append(make_para(cleaned_h1, DOC_TITLE))
        story.append(Spacer(1, 0.15 * cm))
        return
    if kind == "h2":
        payload = _strip_timestamps(payload)
        m = re.match(r"^Chapter\s+(\d+)\s*[-:.—]\s*(.+)$", payload, re.IGNORECASE)
        story.append(Spacer(1, 0.25 * cm))
        story.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceAfter=5, spaceBefore=3))
            
        if m:
            story.append(Paragraph(f"CHAPTER {m.group(1)}", CHAP_LABEL))
            story.append(make_para(m.group(2).strip(), H1))
        else:
            story.append(make_para(payload, H1))
        return
    if kind == "h3":
        cleaned_h3 = _strip_timestamps(payload)
        story.append(make_para(cleaned_h3, H2)); return
    if kind in ("h4", "h5", "h6"):
        cleaned_h4 = _strip_timestamps(payload)
        story.append(make_para(cleaned_h4, H3)); return
    if kind == "p":
        p_elem = make_para(payload, BODY)
        if p_elem.text.strip():
            story.append(p_elem)
        return
    if kind == "ul":
        story.extend(make_ul(payload)); return
    if kind == "ol":
        story.extend(make_ol(payload)); return
    if kind == "diagram":
        try:
            from bot.diagrams import render_diagram_flowable
            dtype, content = payload
            dw = render_diagram_flowable(dtype, content)
            if dw:
                story.append(Spacer(1, 0.2 * cm))
                story.append(dw)
                story.append(Spacer(1, 0.3 * cm))
        except Exception:
            pass
        return
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
        story.append(Spacer(1, 0.2 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=4, spaceBefore=4))
        return


def render(md: str, *, summary_md: str | None = None,
           chapter_titles: list[str] | None = None):
    """Build the flowable list directly on page 1 without wasteful cover page."""
    story: list = []

    if summary_md:
        story.append(Paragraph("OVERVIEW", CHAP_LABEL))
        story.append(Paragraph("Summary at a glance", H1))
        story.extend(make_summary_card(summary_md))

    if chapter_titles:
        story.extend(make_chapter_index(chapter_titles))

    blocks = list(parse_blocks(md))
    for kind, payload in blocks:
        render_block(kind, payload, story)
    return story


def build(src: Path | None = None, out: Path | None = None,
          title: str | None = None, image_base: Path | None = None,
          subtitle: str | None = None,
          features: list[str] | None = None,
          source_url: str | None = None) -> Path:
    """Render the illustrated book.

    ``features`` — opt-in PDF enhancements. None / [] reproduces the
    pre-features PDF byte-for-byte. Supported flags:
      - ``summary``  → extract `<!--SUMMARY-->` block, render as a cover card
      - ``mermaid``  → render `` ```mermaid``` `` code fences via `mmdc` to PNG
      - ``chapters`` → add Chapter Index page + QR code on cover (uses ``source_url``)
      - ``tldr`` / ``qna`` → handled inside the existing markdown parser via
        the two new callout types (no plumbing needed here)

    ``source_url`` — the YouTube URL. Only used by the QR-code half of the
    ``chapters`` feature.
    """
    global IMAGE_BASE, TITLE, SUBTITLE, RUNNING_HEADER, RUNNING_RIGHT, COVER_FOOTER, COVER_TAGLINE, MASTHEAD_PATH, SHOW_QR, SOURCE_URL
    src = Path(src) if src else SRC
    out = Path(out) if out else OUT
    md = src.read_text(encoding="utf-8")

    if title:
        TITLE = title
    else:
        m_title = re.search(r"^#\s+(.+)$", md, re.MULTILINE)
        if m_title:
            TITLE = m_title.group(1).strip()

    SUBTITLE = subtitle or "Comprehensive Master Lecture Handbook"
    RUNNING_HEADER = re.sub(r"[*_`]", "", TITLE)[:65]
    RUNNING_RIGHT = "Master Handbook"
    COVER_FOOTER = "Cheatsheet AI  *  Exhaustive Academic Master Handbook"
    if image_base:
        IMAGE_BASE = Path(image_base)
    feats = set(features or ())

    # Reset opt-in flags
    SHOW_QR = bool(source_url) and ("qr" in feats or "chapters" in feats)
    SOURCE_URL = source_url

    try:
        # --- preprocess for features -------------------------------------------
        summary_md: str | None = None
        if "summary" in feats:
            summary_md, md = _extract_summary_block(md)

        if "mermaid" in feats:
            # Render mermaid blocks BEFORE chapter extraction so the LLM hasn't
            # buried a chapter heading inside a fenced block by mistake. Diagrams
            # are written next to the output PDF in a sibling _diagrams/ dir.
            md = _render_mermaid_blocks(md, out.parent / "_diagrams")

        chapter_titles: list[str] | None = None
        if "chapters" in feats:
            chapter_titles = _extract_chapter_titles(md)

        story = render(md, summary_md=summary_md, chapter_titles=chapter_titles)

        doc = BaseDocTemplate(
            str(out), pagesize=A4,
            leftMargin=MARGIN_L, rightMargin=MARGIN_R,
            topMargin=MARGIN_T, bottomMargin=MARGIN_B,
            title=TITLE, author="Generated student notes",
        )
        frame_body = Frame(MARGIN_L, MARGIN_B, BODY_W,
                           PAGE_H - MARGIN_T - MARGIN_B, id="body", showBoundary=0)
        doc.addPageTemplates([
            PageTemplate(id="body", frames=[frame_body], onPage=body_page),
        ])
        doc.build(story)
        print(f"OK: {out}  ({out.stat().st_size/1024:.1f} kB)")
        return out
    finally:
        # Reset globals
        RUNNING_HEADER = _D_RUNNING_HEADER
        RUNNING_RIGHT = _D_RUNNING_RIGHT
        COVER_FOOTER = _D_COVER_FOOTER
        COVER_TAGLINE = list(_D_COVER_TAGLINE)
        MASTHEAD_PATH = None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_illustrated_book.py <input.md> [output.pdf] [title]")
        sys.exit(0)
    src_arg = Path(sys.argv[1])
    out_arg = Path(sys.argv[2]) if len(sys.argv) > 2 else src_arg.with_suffix('.pdf')
    title_arg = sys.argv[3] if len(sys.argv) > 3 else None
    build(src=src_arg, out=out_arg, title=title_arg)
