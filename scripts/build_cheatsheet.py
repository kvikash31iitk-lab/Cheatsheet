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
MARGIN_L = 1.6 * cm
MARGIN_R = 1.6 * cm
MARGIN_T = 1.4 * cm
MARGIN_B = 1.35 * cm
BODY_W = PAGE_W - MARGIN_L - MARGIN_R

INK = colors.HexColor("#1A1F36")
ACCENT = colors.HexColor("#3A6EA5")
HIGHLIGHT = colors.HexColor("#D97706")
MUTED = colors.HexColor("#5A6172")
RULE = colors.HexColor("#D5DAE0")
PAGE_RULE = colors.HexColor("#DCE3EB")

CALLOUTS = {
    "def":     {"label": "DEF",  "bar": colors.HexColor("#3A6EA5"), "tint": colors.HexColor("#EAF1F8")},
    "example": {"label": "EX",   "bar": colors.HexColor("#2E7D52"), "tint": colors.HexColor("#E8F2EC")},
    "tip":     {"label": "TIP",  "bar": colors.HexColor("#D97706"), "tint": colors.HexColor("#FBF1E1")},
    "warning": {"label": "WARN", "bar": colors.HexColor("#B23A48"), "tint": colors.HexColor("#F8E7E9")},
    "note":    {"label": "NOTE", "bar": colors.HexColor("#5A6172"), "tint": colors.HexColor("#F0F0EE")},
    "revise":  {"label": "TLDR", "bar": colors.HexColor("#3A6EA5"), "tint": colors.HexColor("#F4F1E6")},
    # Added with the v3 feature toggles. tldr = preview at section start;
    # q = Q&A appendix entries. Same hues as the book builder so the visual
    # language is consistent across both PDF formats.
    "tldr":    {"label": "TL;DR", "bar": colors.HexColor("#0D7377"), "tint": colors.HexColor("#E0F2F1")},
    "q":       {"label": "Q",     "bar": colors.HexColor("#7A4F8A"), "tint": colors.HexColor("#F1E8F5")},
}

ss = getSampleStyleSheet()

DOC_TITLE = ParagraphStyle("DocTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                           fontSize=16.2, leading=19, alignment=TA_LEFT,
                           textColor=INK, spaceAfter=3, keepWithNext=1)
DOC_SUB = ParagraphStyle("DocSub", parent=ss["Normal"], fontName="Helvetica-Oblique",
                         fontSize=9.5, leading=12, textColor=MUTED, spaceAfter=7)

H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=12.8, leading=16, textColor=ACCENT,
                    spaceBefore=12, spaceAfter=4, keepWithNext=1,
                    leftIndent=0, borderPadding=(0, 0, 2, 0),
                    borderColor=ACCENT, borderWidth=0)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=11, leading=14, textColor=INK,
                    spaceBefore=8, spaceAfter=3, keepWithNext=1)

BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                      fontSize=9.8, leading=13.5, textColor=INK,
                      alignment=TA_LEFT, spaceAfter=3.5,
                      allowOrphans=0, allowWidows=0)

CO_LABEL = ParagraphStyle("CoLabel", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=8, leading=9.5, textColor=colors.white,
                          spaceAfter=0, alignment=TA_LEFT)
CO_BODY = ParagraphStyle("CoBody", parent=BODY, fontSize=9.2, leading=12.2,
                         spaceAfter=2, alignment=TA_LEFT)

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
    """Convert raw LaTeX math notation like $\text{...} \xrightarrow{...}$ to clean readable text."""
    # Convert \text{word} -> word
    text = re.sub(r"\\text\{([^}]+)\}", r"\1", text)
    # Convert \xrightarrow{condition} -> -> [condition] ->
    text = re.sub(r"\\xrightarrow\{([^}]+)\}", r" -> [\1] -> ", text)
    text = re.sub(r"\\rightarrow", " -> ", text)
    text = re.sub(r"\\neq", " != ", text)
    text = re.sub(r"\\dots", "...", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)  # remove remaining raw LaTeX commands
    # Strip dollar math delimiters
    text = text.replace("$$", "").replace("$", "")
    return text


def inline(text: str) -> str:
    text = _ascii_safe(text)
    text = _clean_latex_math(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Triple asterisks: bold + italic
    text = re.sub(r"\*\*\*(.+?)\*\*\*", rf'<font color="{HIGHLIGHT_HEX}"><b><i>\1</i></b></font>', text)
    # Convert italics first (only when not adjacent to *)
    text = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)
    # Convert bold (and if it wraps any <i> tags, keep them properly nested)
    def _bold_repl(m):
        inner = m.group(1)
        return f'<font color="{HIGHLIGHT_HEX}"><b>{inner}</b></font>'
    text = re.sub(r"\*\*(.+?)\*\*", _bold_repl, text)
    text = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", lambda m: f'<u>{m.group(1)}</u>', text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier" size="8.5" color="#3A6EA5">\1</font>', text)
    return text





CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\](.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")


def parse_blocks(md: str):
    lines = md.splitlines(); i = 0
    while i < len(lines):
        line = lines[i]; stripped = line.strip()
        if not stripped:
            i += 1; continue
        if stripped.startswith("```"):
            lang = stripped.lstrip("`").strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            if i < len(lines):
                i += 1
            yield ("code", (lang, "\n".join(buf))); continue
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
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip())); i += 1
            yield ("ol", items); continue
        if stripped.startswith(("- ", "* ", "+ ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ", "+ ")):
                items.append(lines[i].strip()[2:].strip()); i += 1
            yield ("ul", items); continue
        buf = [stripped]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>|\||---+$|!\[)", lines[i].strip()
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
    """Compact image rendering for the cheatsheet â€” caps at half body height
    so a single mermaid diagram never eats a whole page. Missing files fall
    back to an italic placeholder line so a broken ref never blocks the PDF.
    """
    p = Path(path)
    if not p.is_absolute() or not p.exists():
        return [Paragraph(f"<i>[missing image: {path}]</i>", BODY)]
    try:
        with PILImage.open(p) as im:
            iw, ih = im.size
    except Exception as exc:
        return [Paragraph(f"<i>[image error: {exc}]</i>", BODY)]
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
        out.append(Paragraph(inline(alt), cap))
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
    label = Paragraph(
        "AT A GLANCE",
        ParagraphStyle("SumLabelC", parent=CO_LABEL,
                       textColor=colors.white, fontSize=7.5, leading=9.5),
    )
    body_flowables: list = []
    for k, p in parse_blocks(summary_md):
        if k == "p":
            body_flowables.append(Paragraph(inline(p), body_style))
        elif k == "ul":
            for it in p:
                body_flowables.append(Paragraph(
                    f'<font color="{ACCENT_HEX}"><b>-</b></font> '
                    f'{inline(it)}', bullet_style))
        elif k == "ol":
            for i, it in enumerate(p, 1):
                body_flowables.append(Paragraph(
                    f'<b><font color="{ACCENT_HEX}">{i}.</font></b>'
                    f' {inline(it)}', bullet_style))
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
        # Callout headings are labels, not rich-text bodies. Models sometimes
        # wrap them in Markdown emphasis, which would otherwise print as raw
        # asterisks because this label previously bypassed ``inline``.
        clean_title = re.sub(r"[*_`]", "", title)
        label = f"{label} - {clean_title}"
    pseudo = "\n".join(body_lines)
    body_paras = []
    for k2, p2 in parse_blocks(pseudo):
        if k2 == "p":
            body_paras.append(Paragraph(inline(p2), CO_BODY))
        elif k2 == "ul":
            for it in p2:
                body_paras.append(Paragraph(
                    f'<font color="{ACCENT_HEX}"><b>-</b></font> {inline(it)}',
                    ParagraphStyle("co_li", parent=CO_BODY, leftIndent=10,
                                   firstLineIndent=-10, spaceAfter=1)))
        elif k2 == "ol":
            for n, it in enumerate(p2, 1):
                body_paras.append(Paragraph(
                    f'<b>{n}.</b> {inline(it)}',
                    ParagraphStyle("co_oi", parent=CO_BODY, leftIndent=14,
                                   firstLineIndent=-12, spaceAfter=1)))

    inner = Table([[Paragraph(inline(label), CO_LABEL)]] + [[p] for p in body_paras],
                  colWidths=[BODY_W - 0.3 * cm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), spec["bar"]),
        ("BACKGROUND", (0, 1), (-1, -1), spec["tint"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6.5),
        ("TOPPADDING", (0, 0), (-1, 0), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5),
        ("TOPPADDING", (0, 1), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3.5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, colors.white),
    ]))
    outer = Table([[inner]], colWidths=[BODY_W])
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBEFORE", (0, 0), (0, 0), 2.5, spec["bar"]),
    ]))
    return [Spacer(1, 1), KeepTogether(outer), Spacer(1, 2)]


def make_table(header, rows):
    th = ParagraphStyle("th", parent=BODY, fontName="Helvetica-Bold",
                        fontSize=9.4, leading=11.2, textColor=colors.white,
                        alignment=TA_LEFT, spaceAfter=0)
    td = ParagraphStyle("td", parent=BODY, fontName="Helvetica",
                        fontSize=9.2, leading=11.5, alignment=TA_LEFT, spaceAfter=0)
    data = [[Paragraph(inline(c), th) for c in header]]
    for r in rows:
        data.append([Paragraph(inline(c), td) for c in r])
    col_w = BODY_W / len(header)
    t = Table(data, colWidths=[col_w] * len(header))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, HIGHLIGHT),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, RULE),
    ]))
    return t


def make_ul(items):
    bs = ParagraphStyle("Bul", parent=BODY, leading=13.2, alignment=TA_LEFT,
                        spaceAfter=2.2, leftIndent=12, firstLineIndent=-9)
    return [Paragraph(
        f'<font color="{ACCENT_HEX}"><b>-</b></font> {inline(it)}', bs)
        for it in items]


def make_ol(items):
    ns = ParagraphStyle("Num", parent=BODY, leading=13.2, alignment=TA_LEFT,
                        spaceAfter=2.2, leftIndent=14, firstLineIndent=-12)
    return [Paragraph(
        f'<b><font color="{ACCENT_HEX}">{n}.</font></b> {inline(it)}', ns)
        for n, it in enumerate(items, 1)]


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

def render_block(kind, payload, story):
    if kind == "h1":
        story.append(Paragraph(inline(payload), DOC_TITLE)); return
    if kind == "h2":
        story.append(Paragraph(inline(payload), H1))
        return
    if kind in ("h3", "h4", "h5", "h6"):
        story.append(Paragraph(inline(payload), H2)); return
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
                           textColor=ACCENT, leftIndent=12, rightIndent=12,
                           spaceBefore=2, spaceAfter=4, fontSize=9.4)
        story.append(Paragraph(inline(payload), q)); return
    if kind == "table":
        story.append(Spacer(1, 1))
        story.append(make_table(*payload))
        story.append(Spacer(1, 2)); return
    if kind == "hr":
        story.append(Spacer(1, 2))
        story.append(_rule())
        story.append(Spacer(1, 2))
        return
    if kind == "code":
        lang, code_text = payload
        code_text = _ascii_safe(code_text)
        c_style = ParagraphStyle("CodeBlock", parent=BODY, fontName="Courier",
                                 fontSize=6.5, leading=8.5, textColor=colors.HexColor("#2C3E50"),
                                 backColor=colors.HexColor("#F8F9FA"), borderPadding=4,
                                 borderWidth=0.4, borderColor=colors.HexColor("#E2E8F0"),
                                 borderRadius=3, spaceBefore=3, spaceAfter=3)
        story.append(Preformatted(code_text, c_style))
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
    build()
