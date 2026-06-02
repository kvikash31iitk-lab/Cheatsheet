#!/usr/bin/env python3
"""End-to-end UPSC Cheetsheet pipeline.

Turns an admin-uploaded newspaper PDF into a published Daily Digest. Called
from the FastAPI ``/api/admin/upsc/upload`` endpoint via ``BackgroundTasks``,
and also runnable standalone for manual testing.

State machine (matches ``UpscIssue.status``):

    uploaded -> extracting -> authoring -> rendering -> preview
                                                          |
                                                    [admin clicks Publish]
                                                          v
                                                      published

Stages:
    1. extract  — PDF -> page-by-page text. PyMuPDF first; for subset-font /
                  image PDFs, OCR fallback via Groq Llama 4 Scout.
    2. classify — Drop ads, drop non-UPSC stories. Keep the top 12 candidates.
    3. author   — For each candidate, fill the v2 schema using an LLM call,
                  citing PYQs ONLY from rows fetched via find_pyqs().
    4. render   — Stitch authored markdown together with a digest preamble +
                  annexures, then call build_illustrated_book.build() with the
                  style applier chosen by the admin (default: dense_tight).

CLI (manual testing):

    python scripts/upsc_pipeline.py \\
        --pdf "C:/Users/HP/Downloads/INDIAN EXPRESS HD Delhi 01~06~2026.pdf" \\
        --date 2026-06-01 \\
        --source "Indian Express" \\
        --style dense_tight

    # Already inserted the UpscIssue row via the API, just want to process it:
    python scripts/upsc_pipeline.py --issue-id <hex32>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import fitz  # PyMuPDF  # noqa: E402

from sqlalchemy import select  # noqa: E402

from api.db import SyncSessionLocal, Base, sync_engine  # noqa: E402
from api import models  # noqa: E402  -- registers all tables
from api.models import Pyq, UpscIssue  # noqa: E402
from bot.config import GROQ_API_KEY  # noqa: E402

# Re-use the helpers we already smoke-tested in the seed script.
from scripts.seed_pyq_corpus import (  # noqa: E402
    extract_text as _seed_extract_text,
    ocr_page,
    _safe_json_array,
    _strip_fence,
    _wait_for_429,
)
from scripts import build_illustrated_book as B  # noqa: E402
from scripts.digest_styles import STYLES  # noqa: E402

# Pin classify + author to llama-3.1-8b-instant. The 70B model has tight
# TPM on the Groq free tier (~6K TPM); 8b-instant has ~30K TPM, plenty for
# our structured JSON / per-article extraction. Quality difference is
# unnoticeable for these tasks.
PIPELINE_LLM = "llama-3.1-8b-instant"


def _pipeline_chat(system: str, user: str, *, max_tokens: int = 2500,
                   temperature: float = 0.2) -> str:
    """Groq call pinned to ``PIPELINE_LLM`` (faster + higher TPM than 70B).
    Same retry / 429-hint logic as seed_pyq_corpus._groq_chat."""
    from groq import Groq
    from bot.config import GROQ_API_KEY
    client = Groq(api_key=GROQ_API_KEY)
    last_err = None
    for attempt in range(1, 7):
        try:
            resp = client.chat.completions.create(
                model=PIPELINE_LLM,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            last_err = exc
            wait = _wait_for_429(exc, default_wait=10 * attempt)
            print(f"    pipeline-llm attempt {attempt}/6 failed: waiting {wait:.1f}s — {str(exc)[:140]}")
            time.sleep(wait)
    raise RuntimeError(f"pipeline LLM failed after 6 attempts: {last_err}")

WORK_ROOT = PROJECT_ROOT / "web_work" / "upsc"
WORK_ROOT.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Status helpers
# =============================================================================

def _set_status(issue_id: str, *, status: Optional[str] = None,
                error_message: Optional[str] = None,
                **fields) -> None:
    """Update an UpscIssue row's status + arbitrary fields in one transaction."""
    with SyncSessionLocal() as session:
        row = session.get(UpscIssue, issue_id)
        if row is None:
            raise RuntimeError(f"UpscIssue {issue_id} not found")
        if status is not None:
            row.status = status
        if error_message is not None:
            row.error_message = error_message
        for k, v in fields.items():
            setattr(row, k, v)
        session.commit()


# =============================================================================
# Stage 1: extract
# =============================================================================

def stage_extract(pdf_path: Path) -> str:
    """Extract text from a newspaper PDF. OCR fallback for image-only pages.

    Newspaper PDFs (notably Indian Express HD) use subset fonts where
    PyMuPDF's text layer returns garbled glyphs even though it's "text".
    A character-distribution check catches that and forces OCR.
    """
    doc = fitz.open(pdf_path)
    pages: list[str] = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if _looks_like_real_text(text):
            pages.append(text)
            print(f"  page {i+1}/{len(doc)}: text layer ({len(text)} chars)")
        else:
            pix = page.get_pixmap(dpi=150)
            ocr = ocr_page(pix)
            pages.append(ocr)
            print(f"  page {i+1}/{len(doc)}: OCR ({len(ocr)} chars)")
    doc.close()
    return "\n\f\n".join(pages)


def _looks_like_real_text(text: str) -> bool:
    """Heuristic — is this PyMuPDF text layer usable, or is it subset-font goo?

    A real text layer has high alpha-character density and a reasonable
    char-to-whitespace ratio. Subset-font output tends to be either empty
    or littered with private-use glyphs.
    """
    if len(text) < 200:
        return False
    letters = sum(1 for c in text if c.isalpha())
    if letters / max(len(text), 1) < 0.4:
        return False
    return True


# =============================================================================
# Stage 2: classify (segment + filter)
# =============================================================================

CLASSIFY_SYSTEM = """You are sorting raw newspaper text into UPSC-exam-relevant articles.

Input: the full extracted text of a newspaper issue (multiple pages, ads mixed
in with stories, headers and bylines included).

Output: a JSON array of UPSC-relevant article objects, ordered by exam
relevance (most useful first), with this shape:

{
  "headline":   "<the article's headline, cleaned>",
  "lede":       "<first 2-3 sentences of the article — what happened>",
  "body":       "<the rest of the article, normalised whitespace>",
  "paper":      "GS-1 | GS-2 | GS-3 | GS-4 | essay",
  "static_topics": ["<2-4 tags from the UPSC syllabus, e.g. 'Polity/Federalism'>"],
  "static_link": "<one-line context: which static topic this anchors to>"
}

Rules:
- DROP advertisements, classifieds, sports scores, page-fillers, weather, market
  tickers, horoscopes, recipes, and any story that doesn't touch the GS syllabus.
- DROP "soft" lifestyle pieces unless they are directly about Polity/Economy/IR/
  Environment/S&T/Ethics/Society/Internal Security/Geography/History.
- KEEP every editorial / op-ed / explainer / policy story / verdict / treaty /
  scheme launch / report release / investigation that touches the syllabus.
- Output AT MOST 15 articles. Order by exam relevance, not by page order.
- Output ONLY a JSON array. No prose, no markdown fences.
"""


@dataclass
class Article:
    headline: str
    lede: str
    body: str
    paper: str  # GS-1..GS-4 | essay
    static_topics: list[str]
    static_link: str
    pyqs: list[Pyq] = field(default_factory=list)
    markdown: Optional[str] = None  # filled by stage 3


def stage_classify(extracted_text: str, *, max_articles: int = 12) -> list[Article]:
    """LLM pass that segments + drops + tags. Returns at most max_articles."""
    # Newspaper text can run 50-100K chars. Llama-3.1-8b's free tier wants
    # ~5K tokens per request, so chunk by ~15K chars and merge results.
    # Groq's per-request size limit on the free tier is 6000 tokens TOTAL
    # (input + max_tokens reservation). Newspaper text tokenises at ~1 token
    # per 3 chars (not 4 like English prose), so 3000-char chunks give us
    # ~1000 input tokens + 1500 output reservation + ~500 system = ~3000
    # total, well under the cap with a comfortable buffer.
    chunks = _chunk_text(extracted_text, target_chars=3_000)
    pool: list[Article] = []
    for i, chunk in enumerate(chunks):
        print(f"  classify chunk {i+1}/{len(chunks)} ({len(chunk):,} chars)")
        raw = _pipeline_chat(CLASSIFY_SYSTEM, chunk, max_tokens=1500, temperature=0.2)
        rows = _safe_json_array(raw)
        for r in rows:
            try:
                pool.append(Article(
                    headline=str(r["headline"]).strip(),
                    lede=str(r.get("lede", "")).strip(),
                    body=str(r.get("body", "")).strip(),
                    paper=str(r.get("paper", "GS-2")).strip(),
                    static_topics=[str(t).strip() for t in (r.get("static_topics") or [])][:4],
                    static_link=str(r.get("static_link", "")).strip(),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        time.sleep(2.5)  # polite spacing for Groq's free-tier TPM bucket
    # If the LLM split the same story across chunks, dedupe by headline.
    seen: set[str] = set()
    deduped: list[Article] = []
    for a in pool:
        key = re.sub(r"\W+", "", a.headline.lower())[:40]
        if key in seen or len(key) < 5:
            continue
        seen.add(key)
        deduped.append(a)
    return deduped[:max_articles]


def _chunk_text(text: str, target_chars: int) -> list[str]:
    """Split text into chunks <= ``target_chars``.

    Three-tier split, in priority order: page boundaries (form-feed), then
    paragraph breaks (double newlines), then a hard character cut. The hard
    cut is the safety net — a 20 KB OCR'd page with no paragraph breaks
    must not be sent through whole.
    """
    if len(text) <= target_chars:
        return [text]

    def split_block(block: str, sep: str) -> list[str]:
        """Greedy-pack ``block`` into pieces <= target_chars on ``sep``."""
        out: list[str] = []
        buf: list[str] = []
        size = 0
        for piece in block.split(sep):
            if size + len(piece) > target_chars and buf:
                out.append(sep.join(buf))
                buf, size = [], 0
            buf.append(piece)
            size += len(piece) + len(sep)
        if buf:
            out.append(sep.join(buf))
        return out

    # 1. Greedy-pack by page
    chunks = split_block(text, "\f")
    # 2. Any chunk still too big (one page that exceeds target) — split by paragraph
    refined: list[str] = []
    for c in chunks:
        if len(c) <= target_chars:
            refined.append(c)
        else:
            refined.extend(split_block(c, "\n\n"))
    # 3. Anything still too big after paragraph split — hard character cut.
    final: list[str] = []
    for c in refined:
        if len(c) <= target_chars:
            final.append(c)
        else:
            for i in range(0, len(c), target_chars):
                final.append(c[i:i + target_chars])
    return final


# =============================================================================
# PYQ lookup (the rule: cite only from this corpus, never invent)
# =============================================================================

def find_pyqs(static_topics: list[str], *, limit: int = 3) -> list[Pyq]:
    """Return up to ``limit`` PYQs whose static_topics overlap with the article's.

    Today's implementation is a simple JSON-LIKE match — for each tag in the
    article, pull rows where ``static_topics`` text contains it, then score by
    overlap. Good enough for v1; can upgrade to BM25 later.
    """
    if not static_topics:
        return []
    with SyncSessionLocal() as session:
        candidates: dict[str, tuple[int, Pyq]] = {}
        for tag in static_topics:
            # SQLite LIKE is case-insensitive by default on ASCII. Match either
            # 'Polity/Federalism' or 'Federalism' to handle partial tags.
            head = tag.split("/", 1)[0]
            tail = tag.split("/", 1)[1] if "/" in tag else tag
            for term in {head, tail}:
                like = f"%{term}%"
                rows = session.execute(
                    select(Pyq).where(Pyq.static_topics.like(like)).limit(20)
                ).scalars().all()
                for r in rows:
                    prev = candidates.get(r.id, (0, r))
                    candidates[r.id] = (prev[0] + 1, r)
        ranked = sorted(candidates.values(), key=lambda t: -t[0])
        return [r for _, r in ranked[:limit]]


# =============================================================================
# Stage 3: author (per article)
# =============================================================================

AUTHOR_SYSTEM = """You are writing one article in a UPSC Civil Services daily digest.

You will receive:
  - The newspaper article (headline + lede + body)
  - Its paper-tag (GS-1..GS-4 | essay) and 2-4 static-syllabus topic tags
  - Up to 3 REAL UPSC past-year questions (PYQs) on the same static topic

Produce ONE markdown article in this exact shape (no extra prose, no
preamble):

## {N}. {Headline}

> [!tldr] Why in news
> {1-3 lines on the trigger event — the news hook}

**Paper / GS:** {paper-tag} ({1-3 word slice}) - **Static link:** {static_link}

### Key facts a UPSC answer must carry
| Item | Value / Detail |
|---|---|
| {field} | {value} |
| ... | ... |

### Critical lens
- **For:** {pro argument, 1-2 lines}
- **Against:** {con argument, 1-2 lines}
- **Way forward:** {1-2 lines}

> [!q] Prelims practice
> 1. {MCQ stem with 4 options labelled (a)-(d), correct one bolded}
> 2. {second MCQ}

> [!q] Mains practice ({mark count} marks)
> "{Mains question, 1-2 sentences}"

> [!note] PYQ links
> {bullet list — for EACH supplied PYQ, write one bullet of the form:
>  - **{Stage} {Paper} {Year} ({marks}M):** "{exact question text}"
>  Use the PYQs you were given EXACTLY. If no PYQs were supplied, write the
>  single line: No close PYQ in archive — broader topic last asked recently.
>  NEVER invent a year, marks, or question text.}

Rules:
- The TLDR callout label is "Why in news". Do NOT write "TL;DR".
- Keep the article tight: aim for ~300-450 words across all sections.
- Cite only from the supplied PYQ list. Inventing a PYQ is a critical bug.
- Use Indian-English spellings.
- Numbers and dates from the source article must match the source exactly.
"""


def stage_author(articles: list[Article], *, start_num: int = 1) -> None:
    """Author each article (mutates in place, filling ``markdown``)."""
    for i, art in enumerate(articles):
        n = start_num + i
        print(f"  authoring {n}/{start_num + len(articles) - 1}: {art.headline[:60]!r}")
        # Pull PYQs from the verified corpus
        art.pyqs = find_pyqs(art.static_topics, limit=3)
        prompt = _format_author_prompt(art, n)
        raw = _pipeline_chat(AUTHOR_SYSTEM, prompt, max_tokens=1500, temperature=0.3)
        art.markdown = raw.strip()
        time.sleep(2.5)  # polite spacing for Groq's free-tier TPM bucket


def _format_author_prompt(art: Article, n: int) -> str:
    """Build the user prompt for the authoring LLM call."""
    pyq_block = "\n".join(
        f"- {p.exam_stage.title()} {p.paper} {p.year} ({p.marks}M): \"{p.question_text}\""
        for p in art.pyqs
    ) or "(no close PYQ in archive)"
    return (
        f"Article number: {n}\n"
        f"Headline: {art.headline}\n"
        f"Paper-tag: {art.paper}\n"
        f"Static topics: {', '.join(art.static_topics)}\n"
        f"Static link: {art.static_link}\n\n"
        f"=== Article body ===\n{art.lede}\n\n{art.body}\n\n"
        f"=== Supplied PYQs ===\n{pyq_block}\n"
    )


# =============================================================================
# Stage 4: render
# =============================================================================

def stage_render(
    articles: list[Article],
    *,
    issue_date: date_cls,
    source: str,
    title: str,
    style: str,
    out_path: Path,
    cover_thumb_path: Path,
) -> tuple[int, int]:
    """Compose the full digest markdown and call build_illustrated_book.

    Returns (page_count, file_size_bytes).
    """
    md = _compose_digest_markdown(articles, issue_date=issue_date, source=source)
    md_path = out_path.with_suffix(".md")
    md_path.write_text(md, encoding="utf-8")

    # Apply the chosen style
    if style not in STYLES:
        raise RuntimeError(f"Unknown style: {style}. Must be one of {list(STYLES)}.")
    STYLES[style]()
    B.RUNNING_HEADER = "UPSC CHEETSHEET"
    B.RUNNING_RIGHT = issue_date.strftime("%-d %b %Y") if sys.platform != "win32" else issue_date.strftime("%#d %b %Y")
    B.COVER_TAGLINE = [
        f"{len(articles)} exam-relevant stories distilled for UPSC aspirants.",
        f"Paper-wise tags, static linkage, real PYQs per article.",
    ]
    B.COVER_FOOTER = "Curated for UPSC Civil Services aspirants - cheetsheet.tech"

    issue_url = f"https://cheetsheet.tech/upsc/{issue_date.isoformat()}"
    B.build(
        src=md_path,
        out=out_path,
        title=title,
        subtitle=f"{source} - {issue_date.strftime('%-d %B %Y') if sys.platform != 'win32' else issue_date.strftime('%#d %B %Y')}",
        features=["summary", "tldr", "qna", "chapters"],
        source_url=issue_url,
    )

    # Save a cover thumbnail (page 1 -> PNG) for the public landing card.
    doc = fitz.open(out_path)
    pix = doc[0].get_pixmap(dpi=120)
    pix.save(cover_thumb_path)
    page_count = len(doc)
    doc.close()
    return page_count, out_path.stat().st_size


def _compose_digest_markdown(articles: list[Article], *,
                             issue_date: date_cls, source: str) -> str:
    """Stitch articles together with a digest preamble and annexures."""
    date_str = issue_date.strftime("%-d %B %Y") if sys.platform != "win32" else issue_date.strftime("%#d %B %Y")
    parts: list[str] = []
    parts.append("# UPSC Daily Digest")
    parts.append(f"\n### {source} - {date_str} - for Civil Services aspirants\n")
    parts.append(
        f"This digest filters today's issue of *{source}* down to "
        f"**{len(articles)} exam-relevant stories** — each with paper-wise tags, "
        f"static linkage, key facts, a critical lens, two Prelims-style MCQs, "
        f"one Mains-style question, and **real PYQ links** from the UPSC archive."
    )

    # "Must-read three" callout
    top_three = articles[:3]
    if top_three:
        lines = ["\n> [!revise] Must-read three"]
        for i, a in enumerate(top_three, 1):
            lines.append(f"> {i}. **{a.headline}** — *{a.paper}*. {a.lede[:160]}")
        parts.append("\n".join(lines))

    # Individual articles
    for a in articles:
        if a.markdown:
            parts.append("\n" + a.markdown)

    # Annexure: static + current linkage table
    parts.append("\n## Annexure - Static + current linkage table\n")
    parts.append("| Static topic | Today's anchor | UPSC paper |")
    parts.append("|---|---|---|")
    for a in articles:
        topic = a.static_topics[0] if a.static_topics else "(general)"
        parts.append(f"| {topic} | {a.headline[:60]} | {a.paper} |")
    parts.append("\n*Generated by Cheetsheet UPSC Daily — cheetsheet.tech*")
    return "\n\n".join(parts)


# =============================================================================
# Top-level orchestrator
# =============================================================================

def process_issue(issue_id: str) -> None:
    """The function called from the FastAPI BackgroundTasks queue.

    Reads the UpscIssue row, runs the four stages, updates status after each.
    On any exception, sets status=error + error_message.
    """
    with SyncSessionLocal() as session:
        row = session.get(UpscIssue, issue_id)
        if row is None:
            raise RuntimeError(f"UpscIssue {issue_id} not found")
        pdf_path = Path(row.input_pdf_path)
        issue_date = row.issue_date
        source = row.source
        title = row.title
        style = row.style

    issue_dir = WORK_ROOT / issue_id
    issue_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = issue_dir / "digest.pdf"
    cover_thumb = issue_dir / "cover.png"

    try:
        # ------------------------------------------------------------------ extract
        _set_status(issue_id, status="extracting",
                    extract_seconds=None, classify_seconds=None,
                    author_seconds=None, render_seconds=None)
        print(f"[upsc] {issue_id} stage 1: extract")
        t0 = time.monotonic()
        raw_text = stage_extract(pdf_path)
        extract_dt = time.monotonic() - t0
        print(f"  -> extract took {extract_dt:.1f}s")

        # ------------------------------------------------------------------ classify
        _set_status(issue_id, status="authoring", extract_seconds=extract_dt)
        print(f"[upsc] {issue_id} stage 2: classify")
        t0 = time.monotonic()
        articles = stage_classify(raw_text, max_articles=12)
        classify_dt = time.monotonic() - t0
        print(f"  -> classify took {classify_dt:.1f}s")
        if not articles:
            raise RuntimeError("classify produced 0 articles — bad extraction?")
        print(f"  -> {len(articles)} articles survived classification")

        # ------------------------------------------------------------------ author
        _set_status(issue_id, classify_seconds=classify_dt)
        print(f"[upsc] {issue_id} stage 3: author")
        t0 = time.monotonic()
        stage_author(articles, start_num=1)
        author_dt = time.monotonic() - t0
        print(f"  -> author took {author_dt:.1f}s")

        # ------------------------------------------------------------------ render
        _set_status(issue_id, status="rendering", author_seconds=author_dt)
        print(f"[upsc] {issue_id} stage 4: render")
        t0 = time.monotonic()
        page_count, size_bytes = stage_render(
            articles,
            issue_date=issue_date, source=source,
            title=title, style=style,
            out_path=output_pdf, cover_thumb_path=cover_thumb,
        )
        render_dt = time.monotonic() - t0
        print(f"  -> {output_pdf.name}: {page_count} pages, {size_bytes/1024:.1f} KB ({render_dt:.1f}s)")

        # ------------------------------------------------------------------ preview
        summary = _compose_summary(articles)
        _set_status(
            issue_id, status="preview",
            output_pdf_path=str(output_pdf),
            cover_thumb_path=str(cover_thumb),
            markdown=output_pdf.with_suffix(".md").read_text(encoding="utf-8"),
            summary=summary,
            article_count=len(articles),
            render_seconds=render_dt,
        )
        total = extract_dt + classify_dt + author_dt + render_dt
        print(f"[upsc] {issue_id} -> preview "
              f"(extract={extract_dt:.0f}s · classify={classify_dt:.0f}s · "
              f"author={author_dt:.0f}s · render={render_dt:.0f}s · "
              f"total={total:.0f}s / {total/60:.1f}m)")

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        _set_status(issue_id, status="error", error_message=f"{exc}\n\n{tb}")
        print(f"[upsc] {issue_id} FAILED: {exc}")
        raise


def _compose_summary(articles: list[Article]) -> str:
    """Two-line plain-text summary for the public landing page card."""
    if not articles:
        return ""
    top = articles[0].headline
    paper_counts: dict[str, int] = {}
    for a in articles:
        paper_counts[a.paper] = paper_counts.get(a.paper, 0) + 1
    breakdown = ", ".join(f"{n} {p}" for p, n in sorted(paper_counts.items()))
    return (
        f"Today's lead: {top}. "
        f"{len(articles)} stories total — {breakdown}."
    )


# =============================================================================
# CLI for manual runs
# =============================================================================

def _cli() -> None:
    Base.metadata.create_all(sync_engine)
    if not GROQ_API_KEY:
        sys.exit("ERROR: GROQ_API_KEY missing in .env")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue-id", help="Process an existing UpscIssue row by id.")
    ap.add_argument("--pdf", type=Path, help="Path to a newspaper PDF to process.")
    ap.add_argument("--date", help="Issue date as YYYY-MM-DD (with --pdf).")
    ap.add_argument("--source", default="Indian Express",
                    help="Newspaper source (with --pdf). Default: Indian Express.")
    ap.add_argument("--style", default="dense_tight", choices=list(STYLES),
                    help="Renderer style (with --pdf). Default: dense_tight.")
    ap.add_argument("--title", default=None,
                    help="Override the digest title (with --pdf).")
    args = ap.parse_args()

    if args.issue_id:
        process_issue(args.issue_id)
        return

    if not (args.pdf and args.date):
        sys.exit("Either --issue-id or both --pdf + --date are required.")

    # Insert a fresh UpscIssue row, then process it.
    iso = args.date
    try:
        the_date = date_cls.fromisoformat(iso)
    except ValueError:
        sys.exit(f"--date must be YYYY-MM-DD, got {iso!r}")

    title = args.title or f"UPSC Cheetsheet - {the_date.strftime('%d %B %Y')}"
    import uuid
    new_id = uuid.uuid4().hex
    with SyncSessionLocal() as session:
        row = UpscIssue(
            id=new_id,
            issue_date=the_date,
            source=args.source,
            title=title,
            style=args.style,
            status="uploaded",
            input_pdf_path=str(args.pdf.resolve()),
        )
        session.add(row)
        session.commit()
    print(f"[upsc] inserted UpscIssue {new_id} for {the_date}")
    process_issue(new_id)


if __name__ == "__main__":
    _cli()
