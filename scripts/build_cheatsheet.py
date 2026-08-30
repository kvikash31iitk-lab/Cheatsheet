"""Render a compact 2-3 page cheat-sheet PDF from a markdown source.

A stripped-down sibling of build_illustrated_book.py â€” same callout/markdown
parser, same palette, but:
  - No cover page. Title sits inline at the top of page 1.
  - No automatic page break on h2; sections flow.
  - Tighter margins, smaller body font, denser leading.
  - Image references are silently skipped (this format is text-only).
  - Subtle page header / footer retained for a professional finished look.
"""
from __future__ import annotations

import html
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
from PIL import Image as PILImage

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
SRC = Path(r"C:\Users\HP\Documents\Claude\Video notes\output\cheatsheet.md")
OUT = Path(r"C:\Users\HP\Documents\Claude\Video notes\output\cheatsheet.pdf")
TITLE = "Agentic AI Workflows with Claude Code - Cheat Sheet"
# ============================================================================

PAGE_W, PAGE_H = A4
MARGIN_L = 1.5 * cm
MARGIN_R = 1.5 * cm
MARGIN_T = 1.3 * cm
MARGIN_B = 1.3 * cm
BODY_W = PAGE_W - MARGIN_L - MARGIN_R

INK = colors.HexColor("#000000")        # Pure pitch black ink for laser-sharp print contrast
ACCENT = colors.HexColor("#1D4ED8")     # Deep rich sapphire royal blue
HIGHLIGHT = colors.HexColor("#B45309")  # Warm amber/gold highlight
MUTED = colors.HexColor("#1E293B")      # High contrast dark slate
RULE = colors.HexColor("#CBD5E1")
PAGE_RULE = colors.HexColor("#CBD5E1")


# Multi-color highlight system:
# **text** -> Bold Sapphire/Navy or Amber for facts
# ==text== -> Golden Amber Highlight background tag or colored font
# [red]...[/red], [green]...[/green], [blue]...[/blue], [purple]...[/purple] or tags
COLOR_BLUE = "#1D4ED8"     # Core concepts, statutory references
COLOR_AMBER = "#B45309"    # Key numbers, penalties, deadlines
COLOR_GREEN = "#15803D"    # Valid, approved, positive conditions
COLOR_RED = "#B91C1C"      # Prohibitions, disqualifications, violations
COLOR_PURPLE = "#6D28D9"   # Definitions, authorities, sections
COLOR_TEAL = "#0F766E"     # Case laws, landmark judgments

WHITE_BG = colors.HexColor("#FFFFFF")

CALLOUTS = {
    "def":     {"label": "DEFINITION", "bar": colors.HexColor("#1D4ED8"), "tint": WHITE_BG},
    "example": {"label": "EXAM CASE",  "bar": colors.HexColor("#15803D"), "tint": WHITE_BG},
    "tip":     {"label": "KEY RULE",   "bar": colors.HexColor("#B45309"), "tint": WHITE_BG},
    "warning": {"label": "EXAM TRAP",  "bar": colors.HexColor("#B91C1C"), "tint": WHITE_BG},
    "note":    {"label": "NOTE",       "bar": colors.HexColor("#4B5563"), "tint": WHITE_BG},
    "revise":  {"label": "REVISION",   "bar": colors.HexColor("#0F766E"), "tint": WHITE_BG},
    "tldr":    {"label": "SUMMARY",    "bar": colors.HexColor("#0D7377"), "tint": WHITE_BG},
    "q":       {"label": "QUESTION",   "bar": colors.HexColor("#6D28D9"), "tint": WHITE_BG},
    "correct": {"label": "CORRECT",    "bar": colors.HexColor("#15803D"), "tint": WHITE_BG},
}

ss = getSampleStyleSheet()

DOC_TITLE = ParagraphStyle("DocTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                           fontSize=16.5, leading=20, alignment=TA_LEFT,
                           textColor=INK, spaceAfter=4, keepWithNext=1)
DOC_SUB = ParagraphStyle("DocSub", parent=ss["Normal"], fontName="Helvetica-Oblique",
                         fontSize=9.8, leading=13, textColor=MUTED, spaceAfter=8)

H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=13, leading=16.5, textColor=ACCENT,
                    spaceBefore=11, spaceAfter=4, keepWithNext=1,
                    leftIndent=0, borderPadding=(0, 0, 2, 0),
                    borderColor=ACCENT, borderWidth=0)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=11.2, leading=14.5, textColor=INK,
                    spaceBefore=8, spaceAfter=3.0, keepWithNext=1)

BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                      fontSize=10.0, leading=14.0, textColor=INK,
                      alignment=TA_JUSTIFY, spaceAfter=3.8,
                      allowOrphans=0, allowWidows=0)

CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=8.5, leading=10.5, textColor=colors.white,
                          spaceAfter=0, alignment=TA_LEFT)
CO_BODY = ParagraphStyle("CoBody", parent=BODY, fontSize=9.4, leading=12.8,
                         spaceAfter=2.0, alignment=TA_JUSTIFY, textColor=INK)


ACCENT_HEX = "#" + ACCENT.hexval()[2:]
HIGHLIGHT_HEX = "#" + HIGHLIGHT.hexval()[2:]



def _ascii_safe(text: str) -> str:
    """Replace common model-produced Unicode with Helvetica-safe text."""
    replacements = {
        "\u00a0": " ",
        "\u202f": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2190": "<-",
        "\u2192": "->",
        "\u2194": "<->",
        "\u2248": "~",
        "≈": "~",
        "\u2264": "<=",
        "\u2265": ">=",
        "\u00d7": "x",
        "\u00b1": "+/-",
        "\u20b9": "Rs. ",
        "┌": "+",
        "┐": "+",
        "└": "+",
        "┘": "+",
        "├": "+",
        "┤": "+",
        "┬": "+",
        "┴": "+",
        "┼": "+",
        "│": "|",
        "─": "-",
        "▼": "v",
        "▲": "^",
        "■": "#",
        "█": "#",
        "░": "#",
        "▒": "#",
        "▓": "#",
    }
    return "".join(replacements.get(char, char) for char in text)


def _clean_latex_math(text: str) -> str:
    r"""Convert raw LaTeX math expressions (\frac{}, \approx, \sqrt{}, \text{}, etc.) into clean typography."""
    # 0. Clean set brackets, spacing, and arrows
    text = text.replace(r'\{', '{').replace(r'\}', '}')
    text = text.replace(r'\left\{', '{').replace(r'\right\}', '}')
    text = text.replace(r'\left(', '(').replace(r'\right)', ')')
    text = text.replace(r'\left[', '[').replace(r'\right]', ']')
    text = text.replace(r'\setminus', ' minus ')
    text = re.sub(r'\\(?:q?quad)', '  ', text)
    text = text.replace(r'\,', ' ').replace(r'\;', ' ').replace(r'\:', ' ')
    text = re.sub(r'\\xrightarrow(?:\[(.*?)\])?\{(.*?)\}', r' -> [\2] -> ', text)

    # 1. Un-nest \frac{a}{b} iteratively (up to 5 levels)
    for _ in range(5):
        def repl_frac(m):
            num = m.group(1).strip()
            den = m.group(2).strip()
            has_op = lambda s: any(op in s for op in ['+', '-', '*', '=', '±']) and not (s.startswith('(') and s.endswith(')'))
            num_clean = f"({num})" if has_op(num) else num
            den_clean = f"({den})" if has_op(den) else den
            return f"{num_clean} / {den_clean}" if not (num_clean.startswith('(') and num_clean.endswith(')')) and not (den_clean.startswith('(') and den_clean.endswith(')')) and ' ' not in num_clean and ' ' not in den_clean else f"{num_clean} / {den_clean}"
        text = re.sub(r'\\?(?:frac|tfrac|dfrac)\{([^{}]+)\}\{([^{}]+)\}', repl_frac, text)

    # 2. Text formatting macros
    text = re.sub(r'\\(?:mathrm|textbf|mathbf)\{([^}]+)\}', r'<b>\1</b>', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\(?:mathit|textit)\{([^}]+)\}', r'<i>\1</i>', text)
    text = re.sub(r'\\sqrt\{([^}]+)\}', r'√(\1)', text)
    text = re.sub(r'\\sqrt([0-9a-zA-Z])', r'√\1', text)

    # 3. Greek & math symbols
    symbols = {
        r'\approx': '~', '≈': '~', r'\sim': '~', r'\neq': '!=', r'\ne': '!=',
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

    # 5. Clean up math dollar signs $...$
    text = re.sub(r'\$([^\$]+)\$', r'\1', text)
    text = text.replace('$', '')
    # Strip any dangling LaTeX slashes before words
    text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)
    return text


def inline(text: str) -> str:
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
    # Convert arrows and entities before _ascii_safe
    text = text.replace('→', '&rarr;').replace('←', '&larr;').replace('↔', '&harr;').replace('Δ', '&Delta;').replace('°', '&deg;').replace('≈', '~')

    text = _ascii_safe(text)

    for k, v in sub_map.items():
        text = text.replace(k, v)
    for k, v in sup_map.items():
        text = text.replace(k, v)

    # XML escape before adding HTML tags
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Convert unclosed <br> to self-closing <br/> for ReportLab paraparser compatibility
    text = re.sub(r'&lt;br\s*&gt;', '<br/>', text, flags=re.IGNORECASE)
    # 6. Color spans and markdown highlights:
    # Highlight tag ==text== -> Deep Amber bold
    text = re.sub(r"==([^=]+?)==", rf'<font color="{COLOR_AMBER}"><b>\1</b></font>', text)

    # Color bbcode/markdown tags: [red]...[/red], [green]...[/green], [blue]...[/blue], [purple]...[/purple], [amber]...[/amber], [teal]...[/teal]
    text = re.sub(r"\[red\](.*?)\[/red\]", rf'<font color="{COLOR_RED}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[green\](.*?)\[/green\]", rf'<font color="{COLOR_GREEN}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[blue\](.*?)\[/blue\]", rf'<font color="{COLOR_BLUE}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[purple\](.*?)\[/purple\]", rf'<font color="{COLOR_PURPLE}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[amber\](.*?)\[/amber\]", rf'<font color="{COLOR_AMBER}"><b>\1</b></font>', text, flags=re.IGNORECASE)
    text = re.sub(r"\[teal\](.*?)\[/teal\]", rf'<font color="{COLOR_TEAL}"><b>\1</b></font>', text, flags=re.IGNORECASE)

    # Triple asterisks: bold + italic in rich amber
    text = re.sub(r"\*\*\*(.+?)\*\*\*", rf'<font color="{COLOR_AMBER}"><b><i>\1</i></b></font>', text)
    # Convert italics first (only when not adjacent to *)
    text = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)
    
    # Convert bold: Intelligent semantic coloring
    # Numbers, sections, years, monetary amounts, penalties -> Amber
    # Statutory acts, institutions, judicial cases, Latin maxims -> Royal Blue
    # Prohibitions/Fines/Disqualifications -> Crimson Red
    # Approvals/Exceptions/Permitted -> Emerald Green
    def _bold_repl(m):
        inner = m.group(1).strip()
        # Prohibitions & Warnings
        if re.search(r"\b(prohibit|forbidden|illegal|penalty|fine|imprisonment|punish|disqualif|void|offence|breach|guilty|fail|trap|warning|danger)\b", inner, re.I):
            return f'<font color="{COLOR_RED}"><b>{inner}</b></font>'
        # Statutory sections, articles, acts, institutions
        elif re.search(r"\b(section|sec\.|article|art\.|act|code|tribunal|commission|board|cbt|epfo|ilo|ministry|court|parliament|ordinance)\b", inner, re.I):
            return f'<font color="{COLOR_BLUE}"><b>{inner}</b></font>'
        # Positive / thresholds / approvals
        elif re.search(r"\b(valid|eligible|approved|entitled|exempt|allowed|permitted|benefit|relief|right)\b", inner, re.I):
            return f'<font color="{COLOR_GREEN}"><b>{inner}</b></font>'
        # Numbers, percentages, money, dates, time limits
        elif re.search(r"(\b\d+[\d,\.]*\b|%|rs\.|rupees|days|months|years|hours|timeline|schedule|threshold|ceiling)", inner, re.I):
            return f'<font color="{COLOR_AMBER}"><b>{inner}</b></font>'
        else:
            # Default strong keyword: Rich Navy / Dark Blue
            return f'<font color="#1E3A8A"><b>{inner}</b></font>'
            
    text = re.sub(r"\*\*(.+?)\*\*", _bold_repl, text)
    text = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", lambda m: f'<u>{m.group(1)}</u>', text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier" size="8.5" color="#1E3A8A">\1</font>', text)
    
    # 7. Automatic Statutory Fact Highlighting (Numbers with time/money/percentage units not already enclosed in font tags)
    # Highlights: 7 days, 14 days, 2 months, 6 weeks, 120 days, 50%, Rs. 5000, etc.
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

    
    # Unescape allowed ReportLab tags and normalize anchors (ReportLab paraparser requires <a name="..."> instead of <a id="...">)
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
    text = text.replace("&amp;rarr;", "&rarr;").replace("&amp;larr;", "&larr;").replace("&amp;harr;", "&harr;")
    text = text.replace("&amp;Delta;", "&Delta;").replace("&amp;deg;", "&deg;").replace("&amp;nbsp;", "&nbsp;").replace("&amp;bull;", "&bull;")
    return text


def make_para(text: str, style, bulletText=None) -> Paragraph:
    """Create a ReportLab Paragraph safely with self-healing fallback if XML parsing fails."""
    if text is None:
        return Paragraph("", style, bulletText=bulletText)
    raw_str = str(text)
    if not raw_str.strip():
        return Paragraph("", style, bulletText=bulletText)
    try:
        formatted = inline(raw_str)
        return Paragraph(formatted, style, bulletText=bulletText)
    except Exception:
        # Fallback: Strip broken XML tags and escape raw entities so ReportLab never crashes
        clean = re.sub(r"<[^>]+>", "", raw_str)
        clean = html.escape(clean)
        try:
            return Paragraph(clean, style, bulletText=bulletText)
        except Exception:
            safe_ascii = "".join(c for c in clean if ord(c) < 128)
            return Paragraph(safe_ascii, style, bulletText=bulletText)






def _clean_orphaned_markers(text: str) -> str:
    """Strip dangling bold/italic markers that the LLM left unclosed."""
    s = text.strip()
    if re.fullmatch(r'[\s*_`]+', s):
        return ''
    if s.count('**') % 2 != 0:
        s = s.replace('**', '')
    temp = s.replace('**', '')
    if temp.count('*') % 2 != 0:
        s = re.sub(r'(?<!\*)\*(?!\*)', '', s)
    return s.strip()


def _clean_list_item(text: str) -> str:
    """Sanitize a single bullet / numbered-list item."""
    text = re.sub(r'^[-*+]\s+', '', text.strip())
    text = _clean_orphaned_markers(text)
    return text.strip()


CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\](.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")


def parse_blocks(md: str):
    lines = md.splitlines(); i = 0
    while i < len(lines):
        line = lines[i]; stripped = line.strip()
        if not stripped:
            i += 1; continue

        if re.match(r"^---+$", stripped):
            yield ("hr", None); i += 1; continue
        m_img = IMAGE_RE.match(stripped)
        if m_img:
            # Cheatsheets historically skipped images (text-only format), but
            # the optional `mermaid` feature emits image references for the
            # rendered diagrams. We now yield the block; render_block decides
            # whether to actually draw it (cheap, missing files fall back to
            # an italic placeholder line).
            yield ("image", (m_img.group(1).strip(), m_img.group(2).strip()))
            i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            yield (f"h{len(m.group(1))}", m.group(2).strip()); i += 1; continue
        m = CALLOUT_RE.match(stripped)
        if m:
            kind = m.group(1).lower(); title = m.group(2).strip()
            buf: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            yield ("callout", (kind, title, buf)); continue
        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            yield ("quote", " ".join(b for b in buf if b)); continue
        if "|" in stripped and i + 1 < len(lines) and re.match(r"^[\s\|:\-]+$", lines[i+1].strip()) and "|" in lines[i+1]:
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2; rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            yield ("table", (header, rows)); continue
        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                m_num = re.match(r"^(\d+)\.\s+(.*)$", lines[i].strip())
                if m_num:
                    items.append((int(m_num.group(1)), m_num.group(2).strip()))
                else:
                    items.append((len(items) + 1, re.sub(r"^\d+\.\s+", "", lines[i].strip())))
                i += 1
            yield ("ol", items); continue
        if stripped.startswith(("- ", "* ", "+ ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ", "+ ")):
                cleaned = _clean_list_item(lines[i].strip()[2:].strip())
                if cleaned:
                    items.append(cleaned)
                i += 1
            if items:
                yield ("ul", items)
            continue
        if stripped.startswith("```"):
            fence = stripped[3:].strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                # Break fence early if next line is a module header or major boundary to prevent swallowing
                if re.match(r"^(# Module \d+:|<a id='module-|#\s+Module\s+\d+:)", lines[i].strip()):
                    break
                buf.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip().startswith("```"):
                i += 1
            code_text = "\n".join(buf)
            if fence.startswith("arrangement") or fence.startswith("diagram"):
                yield ("diagram", (fence, code_text))
            else:
                yield ("code", (fence, code_text))
            continue

        buf = [stripped]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>|\||```|---+$|!\[)", lines[i].strip()
        ):
            buf.append(lines[i].strip()); i += 1
        yield ("p", " ".join(buf))


# === opt-in feature support ================================================
# Mirrors the helpers in build_illustrated_book.py â€” same syntax, same
# graceful-degradation contract (missing dependencies log a warning and
# strip the affected block instead of killing the PDF build). See
# bot/cache.py::FEATURE_ORDER for the canonical flag list.

SUMMARY_BLOCK_RE = re.compile(
    r"<!--\s*SUMMARY\s*-->(.*?)<!--\s*/SUMMARY\s*-->",
    re.DOTALL | re.IGNORECASE,
)
MERMAID_FENCE_RE = re.compile(
    r"^```mermaid\s*\n(.*?)^```\s*$",
    re.DOTALL | re.MULTILINE,
)

# Cover-side QR + URL â€” set by build() when the `chapters` feature is on AND
# source_url was provided. The page() callback reads these as globals
# because ReportLab's PageTemplate callback signature is fixed.
SHOW_QR: bool = False
SOURCE_URL: str | None = None
DOC_RUNTIME_TITLE: str = TITLE


def _extract_summary_block(md: str) -> tuple[str | None, str]:
    """Pull the `<!--SUMMARY-->` block out. Returns (summary_md, cleaned_md)."""
    m = SUMMARY_BLOCK_RE.search(md)
    if not m:
        return None, md
    return m.group(1).strip(), md[:m.start()] + md[m.end():]


def _strip_summary_markers(md: str) -> str:
    """Keep summary content while removing authoring-only HTML markers."""

    return SUMMARY_BLOCK_RE.sub(lambda match: match.group(1).strip(), md)


# Puppeteer config â€” see build_illustrated_book.py for the rationale.
_MMDC_PUPPETEER_CONFIG = Path(__file__).resolve().parent / "mmdc-puppeteer.json"


def _render_mermaid_blocks(md: str, out_dir: Path) -> str:
    """Render `` ```mermaid``` `` fences to PNGs via `mmdc`, swap fence for
    image ref. No-op if no fences found or `mmdc` is missing."""
    if not MERMAID_FENCE_RE.search(md):
        return md
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
               "-b", "white", "-w", "1200", "-H", "750"]
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
        first = next((l.strip() for l in src.splitlines() if l.strip()), "")
        caption = ("Concept mindmap" if first.lower().startswith("mindmap")
                   else "Process flowchart" if first.lower().startswith(("flowchart", "graph"))
                   else "Diagram")
        return f"\n\n![{caption}]({out_file.resolve().as_posix()})\n\n"

    return MERMAID_FENCE_RE.sub(_repl, md)


def _make_qr_image_reader(url: str, *, box: int = 6, border: int = 2):
    """In-memory QR code as a ReportLab ImageReader. None if `qrcode` lib
    isn't installed (graceful no-op)."""
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


def make_image_flowable(alt: str, path: str) -> list:
    """Compact image rendering for the cheatsheet — caps at half body height
    so a single mermaid diagram never eats a whole page. Missing files fall
    back to an italic placeholder line so a broken ref never blocks the PDF.
    """
    p = Path(path)
    if not p.is_absolute() or not p.exists():
        return [make_para(f"<i>[missing image: {path}]</i>", BODY)]
    try:
        with PILImage.open(p) as im:
            iw, ih = im.size
    except Exception as exc:
        return [make_para(f"<i>[image error: {exc}]</i>", BODY)]
    max_w = BODY_W
    max_h = (PAGE_H - MARGIN_T - MARGIN_B) * 0.40  # cheatsheets stay tight
    scale = min(max_w / iw, max_h / ih, 1.0)
    img = Image(str(p.resolve()), width=iw * scale, height=ih * scale)
    img.hAlign = "CENTER"
    out: list = [Spacer(1, 2), img]
    if alt:
        cap = ParagraphStyle("ImgCap", parent=BODY, fontSize=8.5,
                             leading=10, alignment=TA_CENTER,
                             textColor=MUTED, spaceBefore=2, spaceAfter=4)
        out.append(make_para(alt, cap))
    return [KeepTogether(out)]


def make_summary_card_compact(summary_md: str) -> list:
    """Tight summary card sized for the cheatsheet's denser layout. Same
    parsing rules as the book builder's full-size version."""
    body_style = ParagraphStyle(
        "SumBodyC", parent=BODY, fontSize=9.4, leading=12.5,
        textColor=INK, spaceAfter=2, alignment=TA_LEFT,
    )
    bullet_style = ParagraphStyle(
        "SumBullC", parent=body_style, leftIndent=10,
        firstLineIndent=-9, spaceAfter=1.5,
    )
    label = make_para(
        "AT A GLANCE",
        ParagraphStyle("SumLabelC", parent=CO_LABEL,
                       textColor=colors.white, fontSize=7.5, leading=9.5),
    )
    body_flowables: list = []
    for k, p in parse_blocks(summary_md):
        if k == "p":
            body_flowables.append(make_para(p, body_style))
        elif k == "ul":
            for it in p:
                body_flowables.append(make_para(
                    f'<font color="{ACCENT_HEX}"><b>-</b></font> '
                    f'{it}', bullet_style))
        elif k == "ol":
            for i, it in enumerate(p, 1):
                body_flowables.append(make_para(
                    f'<b><font color="{ACCENT_HEX}">{i}.</font></b>'
                    f' {it}', bullet_style))
    rows = [[label]] + [[fl] for fl in body_flowables]
    card = Table(rows, colWidths=[BODY_W - 0.2 * cm])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    return [KeepTogether(card), Spacer(1, 6)]


def make_callout(kind: str, title: str, body_lines: list[str]) -> list:
    spec = CALLOUTS.get(kind, CALLOUTS["note"])
    label = spec["label"]
    if title:
        clean_title = re.sub(r"[*_`]", "", title)
        label = f"{label} - {clean_title}"
    pseudo = "\n".join(body_lines)
    body_paras = []
    for k2, p2 in parse_blocks(pseudo):
        if k2 == "p":
            body_paras.append(make_para(p2, CO_BODY))
        elif k2 == "ul":
            for it in p2:
                body_paras.append(make_para(
                    f'<font color="{ACCENT_HEX}"><b>-</b></font> {it}',
                    ParagraphStyle("co_li", parent=CO_BODY, leftIndent=10,
                                   firstLineIndent=-10, spaceAfter=1)))
        elif k2 == "ol":
            for it in p2:
                num, text_val = (it[0], it[1]) if (isinstance(it, tuple) and len(it) == 2) else (1, it)
                body_paras.append(make_para(
                    f'<b>{num}.</b> {text_val}',
                    ParagraphStyle("co_oi", parent=CO_BODY, leftIndent=14,
                                   firstLineIndent=-12, spaceAfter=1)))

    inner = Table([[make_para(label, CO_LABEL)]] + [[p] for p in body_paras],
                  colWidths=[BODY_W - 0.3 * cm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), spec["bar"]),
        ("BACKGROUND", (0, 1), (-1, -1), spec["tint"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3.5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.white),
        ("BOX", (0, 0), (-1, -1), 0.4, spec["bar"]),
    ]))
    outer = Table([[inner]], colWidths=[BODY_W])
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBEFORE", (0, 0), (0, 0), 3.0, spec["bar"]),
    ]))
    return [Spacer(1, 2), KeepTogether(outer), Spacer(1, 3)]


def make_table(header, rows):
    th = ParagraphStyle("th", parent=BODY, fontName="Helvetica-Bold",
                        fontSize=9.5, leading=12.2, textColor=colors.white,
                        alignment=TA_LEFT, spaceAfter=0)
    td = ParagraphStyle("td", parent=BODY, fontName="Helvetica",
                        fontSize=9.2, leading=12.2, alignment=TA_JUSTIFY, spaceAfter=0, textColor=INK)
    data = [[make_para(c, th) for c in header]]
    for r in rows:
        data.append([make_para(c, td) for c in r])
    col_w = BODY_W / len(header)
    t = Table(data, colWidths=[col_w] * len(header), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E2E8F0")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.HexColor("#1E3A8A")),
    ]))
    return KeepTogether(t)



def make_ul(items):
    bs = ParagraphStyle("Bul", parent=BODY, leading=14.2, alignment=TA_JUSTIFY,
                        spaceAfter=3.0, leftIndent=12, firstLineIndent=-9, textColor=INK)
    return [make_para(
        f'<font color="{ACCENT_HEX}"><b>&bull;</b></font> {it}', bs)
        for it in items]



def make_ol(items):
    ns = ParagraphStyle("Num", parent=BODY, leading=14.2, alignment=TA_JUSTIFY,
                        spaceAfter=3.0, leftIndent=14, firstLineIndent=-12, textColor=INK)
    res = []
    for item in items:
        if isinstance(item, tuple) and len(item) == 2:
            num, it = item
        else:
            num, it = 1, item
        res.append(make_para(f'<b><font color="{ACCENT_HEX}">{num}.</font></b> {it}', ns))
    return res



def _rule() -> Table:
    return Table(
        [[""]],
        colWidths=[BODY_W],
        style=TableStyle([
            ("LINEABOVE", (0, 0), (-1, -1), 0.45, PAGE_RULE),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
    )


def page(canv, doc):
    canv.saveState()

    # Header band.
    canv.setFillColor(PAGE_RULE)
    canv.rect(
        MARGIN_L,
        PAGE_H - MARGIN_T + 0.13 * cm,
        BODY_W,
        0.35 * cm,
        fill=1,
        stroke=0,
    )
    canv.setFillColor(ACCENT)
    canv.setFont("Helvetica-Bold", 8)
    canv.drawString(
        MARGIN_L + 0.12 * cm,
        PAGE_H - MARGIN_T + 0.26 * cm,
        "CHEETSHEET",
    )
    canv.setFont("Helvetica", 7.2)
    canv.setFillColor(MUTED)
    canv.drawRightString(
        PAGE_W - MARGIN_R - 0.1 * cm,
        PAGE_H - MARGIN_T + 0.24 * cm,
        DOC_RUNTIME_TITLE[:48],
    )

    # Footer page number + subtle divider.
    canv.setFillColor(RULE)
    canv.setLineWidth(0.4)
    canv.line(MARGIN_L, 0.95 * cm, PAGE_W - MARGIN_R, 0.95 * cm)
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica-Oblique", 7.4)
    canv.drawString(MARGIN_L, 0.58 * cm, "Generated by cheetsheet.tech")
    canv.drawCentredString(PAGE_W / 2, 0.58 * cm, f"Page {doc.page}")
    if DOC_RUNTIME_TITLE:
        canv.drawRightString(PAGE_W - MARGIN_R, 0.58 * cm, DOC_RUNTIME_TITLE[:36])

    # Optional QR on page 1 only (top-right corner) â€” opt-in via the
    # `chapters` feature. The cheatsheet is short so a single QR on page 1
    # is enough; repeating it on page 2/3 would just waste space.
    if SHOW_QR and SOURCE_URL and doc.page == 1:
        qr = _make_qr_image_reader(SOURCE_URL)
        if qr is not None:
            size = 1.4 * cm
            x = PAGE_W - MARGIN_R - size
            y = PAGE_H - MARGIN_T - size + 0.05 * cm
            canv.drawImage(qr, x, y, width=size, height=size, mask="auto")
            canv.setFillColor(MUTED)
            canv.setFont("Helvetica", 5.5)
            canv.drawCentredString(x + size / 2, y - 0.22 * cm, "source video")
    canv.restoreState()

def _parse_ascii_table(code_text: str):
    """Detect and parse ASCII grid tables into native header and rows."""
    lines = [l for l in code_text.strip().split('\n') if l.strip()]
    if len(lines) < 3:
        return None
    border_lines = [l for l in lines if l.startswith('+') and '-' in l]
    if len(border_lines) < 2:
        return None
    
    first_b = border_lines[0]
    col_starts = [i for i, ch in enumerate(first_b) if ch == '+']
    if len(col_starts) < 3:  # Need at least 2 columns (+---+---+)
        return None
    
    raw_rows = []
    curr_cells = []
    
    for l in lines[1:]:
        if l.startswith('+') and '-' in l:
            if curr_cells:
                row = [' '.join(c).strip().rstrip('|').strip() for c in curr_cells]
                if any(row):
                    raw_rows.append(row)
                curr_cells = []
            continue
        if '|' in l:
            pieces = []
            for i in range(len(col_starts) - 1):
                s = col_starts[i] + 1
                e = col_starts[i+1] if col_starts[i+1] < len(l) else len(l)
                cell_txt = l[s:e].strip().rstrip('|').strip() if s < len(l) else ''
                pieces.append(cell_txt)
            if not curr_cells:
                curr_cells = [[p] for p in pieces]
            else:
                for i, p in enumerate(pieces):
                    if i < len(curr_cells) and p:
                        curr_cells[i].append(p)
    if curr_cells:
        row = [' '.join(c).strip().rstrip('|').strip() for c in curr_cells]
        if any(row):
            raw_rows.append(row)
            
    if len(raw_rows) >= 2:
        return raw_rows[0], raw_rows[1:]
    return None


def render_block(kind, payload, story):
    if kind == "h1":
        story.append(make_para(payload, DOC_TITLE)); return
    if kind == "h2":
        story.append(make_para(payload, H1))
        return
    if kind in ("h3", "h4", "h5", "h6"):
        story.append(make_para(payload, H2)); return
    if kind == "p":
        story.append(make_para(payload, BODY)); return
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
                           textColor=ACCENT, leftIndent=12, rightIndent=12,
                           spaceBefore=2, spaceAfter=4, fontSize=9.5)
        story.append(make_para(payload, q)); return
    if kind == "table":
        story.append(Spacer(1, 1))
        story.append(make_table(*payload))
        story.append(Spacer(1, 2)); return
    if kind == "hr":
        story.append(Spacer(1, 2))
        story.append(_rule())
        story.append(Spacer(1, 2))
        return
    if kind == "diagram":
        fence, code_text = payload
        try:
            from bot.diagrams import render_diagram_flowable
            diag_f = render_diagram_flowable(fence, code_text)
            if diag_f:
                story.append(Spacer(1, 2))
                story.append(diag_f)
                story.append(Spacer(1, 4))
                return
        except Exception:
            pass
        return
    if kind == "code":
        lang, code_text = payload
        code_text = _ascii_safe(code_text)
        
        # 1. If it's an ASCII grid table -> convert directly into a high-visibility native Table!
        parsed_table = _parse_ascii_table(code_text)
        if parsed_table:
            story.append(Spacer(1, 2))
            story.append(make_table(parsed_table[0], parsed_table[1]))
            story.append(Spacer(1, 3))
            return

        # 2. For ASCII diagrams, trees, and code blocks -> Deep Black Courier-Bold with crisp contrast
        is_diagram_tree = any(sym in code_text for sym in ("|", "-->", "->", "+--", "+==", "v", "^", "\\", "/"))
        font_sz = 8.0 if is_diagram_tree else 8.5
        line_height = 10.5 if is_diagram_tree else 11.5
        
        c_style = ParagraphStyle("CodeBlock", parent=BODY, fontName="Courier-Bold",
                                 fontSize=font_sz, leading=line_height, textColor=colors.HexColor("#000000"),
                                 backColor=colors.HexColor("#F1F5F9"), borderPadding=6,
                                 borderWidth=0.8, borderColor=colors.HexColor("#94A3B8"),
                                 borderRadius=4, spaceBefore=4, spaceAfter=4)
        story.append(KeepTogether(Preformatted(code_text, c_style)))
        return




def render(md: str, *, summary_md: str | None = None):
    """Build the flowable list. ``summary_md`` â€” if non-None, render the
    compact summary card at the very top of page 1 (before the title)."""
    story: list = []
    if summary_md:
        story.extend(make_summary_card_compact(summary_md))
    for kind, payload in parse_blocks(md):
        render_block(kind, payload, story)
    return story


def build(src: Path | None = None, out: Path | None = None,
          title: str | None = None,
          features: list[str] | None = None,
          source_url: str | None = None) -> Path:
    """Render the cheatsheet.

    ``features`` â€” opt-in PDF enhancements. None / [] reproduces the
    pre-features PDF byte-for-byte. Supported flags:
      - ``summary``  â†’ extract `<!--SUMMARY-->` block, render at top of page 1
      - ``mermaid``  â†’ render `` ```mermaid``` `` code fences via `mmdc` to PNG
      - ``chapters`` â†’ QR code on page 1 (cheatsheet is too short for a TOC,
        so we use the flag for the URL bridge only â€” same flag works on
        both PDF kinds so the UI can stay consistent)
      - ``tldr`` / ``qna`` â†’ handled by the existing callout parser via the
        two new callout types added to ``CALLOUTS``
    """
    global SHOW_QR, SOURCE_URL, DOC_RUNTIME_TITLE
    src = Path(src) if src else SRC
    out = Path(out) if out else OUT
    title = title or TITLE
    feats = set(features or ())

    SHOW_QR = bool(source_url) and "chapters" in feats
    SOURCE_URL = source_url
    DOC_RUNTIME_TITLE = title

    md = src.read_text(encoding="utf-8")

    # --- preprocess for features -------------------------------------------
    summary_md: str | None = None
    if "summary" in feats:
        summary_md, md = _extract_summary_block(md)
    else:
        md = _strip_summary_markers(md)

    if "mermaid" in feats:
        md = _render_mermaid_blocks(md, out.parent / "_diagrams")

    story = render(md, summary_md=summary_md)

    doc = BaseDocTemplate(
        str(out), pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T, bottomMargin=MARGIN_B,
        title=title, author="Generated cheat sheet",
    )
    frame = Frame(MARGIN_L, MARGIN_B, BODY_W,
                  PAGE_H - MARGIN_T - MARGIN_B, id="body", showBoundary=0)
    # Draw furniture after flowables. Split tables/callouts can otherwise
    # paint an opaque continuation background over header/footer elements.
    doc.addPageTemplates([PageTemplate(id="body", frames=[frame], onPageEnd=page)])
    doc.build(story)
    print(f"OK: {out}  ({out.stat().st_size/1024:.1f} kB)")
    return out


if __name__ == "__main__":
    src_arg = sys.argv[1] if len(sys.argv) > 1 else None
    out_arg = sys.argv[2] if len(sys.argv) > 2 else None
    build(src=src_arg, out=out_arg)
