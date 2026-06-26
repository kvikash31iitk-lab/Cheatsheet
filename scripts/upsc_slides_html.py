"""Render the digest markdown into the branded 16:9 'Clean' deck (matching the
UPSC Cheetsheet PPTX) as 1920x1080 PNG slides, via headless Chromium (Playwright).

Slide order = [title, article-1 … article-N, outro] so it aligns 1:1 with the
narration sections (intro + one per article + outro) produced by upsc_narration.

Public API:  render(md_text, out_dir, *, date_label="", source="", theme="amber")
             -> list[Path]   (the slide PNGs in order)
"""
from __future__ import annotations

import html
import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# Markdown parsing
# --------------------------------------------------------------------------- #

GS_COLORS = {"GS-1": "#d2691e", "GS-2": "#3b6fd4", "GS-3": "#2e8b57",
             "GS-4": "#9b59b6", "GS-1/2": "#d2691e"}


def _clean(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)      # bold
    s = re.sub(r"\*(.+?)\*", r"\1", s)          # italic
    s = re.sub(r"`(.+?)`", r"\1", s)            # code
    return s.strip()


def parse_digest(md: str) -> dict:
    lines = md.split("\n")
    meta = {"source": "", "date": "", "subtitle": "", "articles": []}

    # source/date line: "### {Source} - {date} - for ..."
    for ln in lines[:12]:
        m = re.match(r"^###\s+(.+?)\s+-\s+(.+?)\s+-\s+", ln)
        if m:
            meta["source"], meta["date"] = m.group(1).strip(), m.group(2).strip()
            break

    # subtitle = first normal paragraph before the first "## "
    head = md.split("\n## ", 1)[0]
    for para in head.split("\n\n"):
        p = para.strip()
        if p and not p.startswith(("#", ">", "|")):
            meta["subtitle"] = _clean(p)
            break

    # article blocks
    blocks = re.split(r"\n##\s+\d+\.\s+", "\n" + md)[1:]
    for i, blk in enumerate(blocks, 1):
        b = ("## " + blk) if not blk.startswith("##") else blk
        a = {"n": i, "headline": "", "gs": "", "slice": "", "why": "",
             "static": "", "facts": [], "for": "", "against": "", "way": ""}
        first = blk.split("\n", 1)[0]
        a["headline"] = _clean(first)

        m = re.search(r"\[!tldr\][^\n]*\n((?:>.*\n?)+)", blk)
        if m:
            a["why"] = _clean(re.sub(r"^>\s?", "", m.group(1), flags=re.M).replace("\n", " "))

        m = re.search(r"Paper\s*/\s*GS:\**\s*(GS-[\d/]+)\s*\(([^)]+)\)", blk)
        if m:
            a["gs"], a["slice"] = m.group(1), m.group(2).strip()
        m = re.search(r"Static link:\**\s*(.+)", blk)
        if m:
            a["static"] = _clean(m.group(1))

        # key-facts table
        kf = re.search(r"Key facts[^\n]*\n((?:\|.*\n?)+)", blk)
        if kf:
            rows = [r for r in kf.group(1).split("\n") if r.strip().startswith("|")]
            for r in rows:
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                if len(cells) >= 2 and "---" not in cells[0] and cells[0].lower() != "item":
                    a["facts"].append((_clean(cells[0]), _clean(cells[1])))

        for key, lab in (("for", "For"), ("against", "Against"), ("way", "Way forward")):
            mm = re.search(rf"-\s*\*\*{lab}:\*\*\s*(.+)", blk)
            if mm:
                a[key] = _clean(mm.group(1))
        meta["articles"].append(a)
    return meta


# --------------------------------------------------------------------------- #
# HTML / CSS  (matches the PPTX deck: dark warm bg, serif headlines, mono labels)
# --------------------------------------------------------------------------- #

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@600;700&family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px}
body{background:#1a1613;color:#f3ecdd;font-family:'Inter',sans-serif;overflow:hidden}
.slide{width:1920px;height:1080px;padding:96px 110px;display:flex;flex-direction:column;position:relative}
.mono{font-family:'JetBrains Mono',monospace;letter-spacing:.18em;text-transform:uppercase}
.serif{font-family:'Source Serif 4',serif}
.muted{color:#8c8377}.amber{color:#cfa64e}
.head{display:flex;justify-content:space-between;font-size:24px}
.foot{position:absolute;left:110px;right:110px;bottom:84px;display:flex;justify-content:space-between;align-items:center;font-size:22px}
.dot{display:inline-block;width:13px;height:13px;border-radius:50%;margin-right:9px;vertical-align:middle}
.gstag{display:inline-block;font-family:'JetBrains Mono',monospace;font-weight:600;font-size:20px;letter-spacing:.12em;color:#fff;padding:5px 13px;border-radius:7px}
/* title slide */
.t-label{font-size:28px;margin-bottom:26px}
.t-title{font-size:104px;font-weight:700;line-height:1.02;margin-bottom:40px}
.t-sub{font-size:33px;line-height:1.5;color:#cfc7b8;max-width:1400px}
/* article slide */
.a-head{display:flex;align-items:center;gap:22px;font-size:24px;margin-bottom:18px}
.a-num{font-family:'Source Serif 4',serif;font-size:30px;color:#6b6358}
.a-title{font-size:50px;font-weight:700;line-height:1.08;margin-bottom:16px}
.a-why{font-size:26px;line-height:1.45;color:#bdb4a4;max-width:1640px;margin-bottom:26px}
.rule{height:1px;background:#3a342c;margin-bottom:30px}
.cols{display:grid;grid-template-columns:38% 1fr;gap:64px;flex:1;min-height:0}
.colhead{font-size:22px;margin-bottom:22px;color:#8c8377}
.fact{display:grid;grid-template-columns:200px 1fr;gap:18px;margin-bottom:16px;font-size:24px;line-height:1.3}
.fact .k{color:#cfa64e;font-family:'JetBrains Mono',monospace;font-size:18px;text-transform:uppercase;letter-spacing:.04em;padding-top:2px}
.fact .v{color:#e9e1d2}
.lens{display:grid;grid-template-columns:repeat(3,1fr);gap:40px}
.lens .ll{font-family:'JetBrains Mono',monospace;font-size:19px;letter-spacing:.1em;margin-bottom:14px}
.lens .lt{font-size:23px;line-height:1.4;color:#d8d0c1}
.lfor .ll{color:#2e8b57}.lag .ll{color:#c0552f}.lway .ll{color:#cfa64e}
"""


def _gs_pill(gs: str) -> str:
    color = GS_COLORS.get(gs, "#6b6358")
    return f'<span class="gstag" style="background:{color}">{html.escape(gs or "GS")}</span>'


def _slide(body: str) -> str:
    return f'<div class="slide">{body}</div>'


def html_title(meta: dict) -> str:
    src = (meta.get("source") or "Daily Digest").upper()
    date = (meta.get("date") or "").upper()
    sub = html.escape(meta.get("subtitle") or "")
    legend = ("".join(f'<span style="margin-right:34px"><span class="dot" '
              f'style="background:{GS_COLORS[g]}"></span>{g}</span>'
              for g in ("GS-1", "GS-2", "GS-3")))
    body = (
        '<div class="head mono muted"><span>UPSC Cheetsheet</span><span>Daily Digest</span></div>'
        '<div style="flex:1;display:flex;flex-direction:column;justify-content:center">'
        f'<div class="t-label mono amber">{html.escape(src)} &middot; {html.escape(date)}</div>'
        '<div class="t-title serif">Daily Current Affairs Digest</div>'
        f'<div class="t-sub">{sub}</div>'
        '</div>'
        f'<div class="foot"><div class="mono muted">{legend}</div>'
        '<div class="mono muted">cheetsheet.tech/upsc</div></div>'
    )
    return _slide(body)


def html_article(a: dict) -> str:
    facts = "".join(
        f'<div class="fact"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}</div></div>'
        for k, v in a["facts"][:7]
    )
    lens = (
        f'<div class="lfor"><div class="ll">For</div><div class="lt">{html.escape(a["for"])}</div></div>'
        f'<div class="lag"><div class="ll">Against</div><div class="lt">{html.escape(a["against"])}</div></div>'
        f'<div class="lway"><div class="ll">Way Forward</div><div class="lt">{html.escape(a["way"])}</div></div>'
    )
    label = html.escape((a.get("slice") or "").upper())
    body = (
        f'<div class="a-head"><span class="a-num">{a["n"]:02d}</span>{_gs_pill(a["gs"])}'
        f'<span class="mono muted">{label}</span></div>'
        f'<div class="a-title serif">{html.escape(a["headline"])}</div>'
        f'<div class="a-why">{html.escape(a["why"])}</div>'
        '<div class="rule"></div>'
        '<div class="cols">'
        f'<div><div class="colhead mono">Key Facts</div>{facts}</div>'
        f'<div><div class="colhead mono">Critical Lens</div><div class="lens">{lens}</div></div>'
        '</div>'
        f'<div class="foot"><div class="mono muted">Static link &middot; {html.escape(a.get("gs") or "")}</div>'
        '<div class="mono muted">cheetsheet.tech/upsc</div></div>'
    )
    return _slide(body)


def html_outro(meta: dict) -> str:
    body = (
        '<div class="head mono muted"><span>UPSC Cheetsheet</span><span>Daily Digest</span></div>'
        '<div style="flex:1;display:flex;flex-direction:column;justify-content:center">'
        '<div class="t-label mono amber">That\'s today\'s digest</div>'
        '<div class="t-title serif" style="font-size:88px">Revise. Reflect.<br>Repeat tomorrow.</div>'
        '<div class="t-sub">Full digest, MCQs and PYQ links at cheetsheet.tech/upsc</div>'
        '</div>'
        '<div class="foot"><div class="mono muted">Subscribe for the daily UPSC digest</div>'
        '<div class="mono muted">cheetsheet.tech/upsc</div></div>'
    )
    return _slide(body)


# --------------------------------------------------------------------------- #
# Render via Playwright
# --------------------------------------------------------------------------- #

def render(md_text: str, out_dir: str | Path, *, theme: str = "amber") -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = parse_digest(md_text)
    pages_html = [html_title(meta)]
    pages_html += [html_article(a) for a in meta["articles"]]
    pages_html.append(html_outro(meta))

    from playwright.sync_api import sync_playwright
    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=1)
        for i, body in enumerate(pages_html):
            page.set_content(f"<!doctype html><html><head><meta charset='utf-8'>"
                             f"<style>{CSS}</style></head><body>{body}</body></html>",
                             wait_until="networkidle")
            page.wait_for_timeout(250)  # let webfonts settle
            out = out_dir / f"slide-{i:02d}.png"
            page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
            paths.append(out)
        browser.close()
    return paths


if __name__ == "__main__":
    import sys
    md = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/clean_slides"
    ps = render(md, out)
    print(f"rendered {len(ps)} slides -> {out}")
