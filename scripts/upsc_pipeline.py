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


# If Groq hints a wait longer than this, treat as a daily-quota wall (TPD)
# rather than a transient TPM blip: don't keep retrying — fail fast so the
# admin can re-trigger after the rolling window resets. Daily walls return
# multi-minute / hour-long hints; legitimate TPM congestion returns <60s.
PIPELINE_LONG_WAIT_THRESHOLD = 90.0


def _pipeline_chat(system: str, user: str, *, max_tokens: int = 2500,
                   temperature: float = 0.2) -> str:
    """Groq call pinned to ``PIPELINE_LLM`` (faster + higher TPM than 70B).
    Same retry / 429-hint logic as seed_pyq_corpus._groq_chat — but bails out
    early if Groq returns a long wait hint (means daily-quota wall, not TPM)."""
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
            if wait > PIPELINE_LONG_WAIT_THRESHOLD:
                raise RuntimeError(
                    f"pipeline LLM hit daily-quota wall (Groq asked to wait "
                    f"{wait:.0f}s = {wait/60:.1f}min): {str(exc)[:200]}"
                ) from exc
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

def stage_extract(pdf_path: Path, *, ocr_workers: int = 4) -> str:
    """Extract text from a newspaper PDF. OCR fallback for image-only pages.

    Newspaper PDFs (notably Indian Express HD) use subset fonts where
    PyMuPDF's text layer returns garbled glyphs even though it's "text".
    A character-distribution check catches that and forces OCR.

    OCR runs in parallel via a ThreadPoolExecutor — Tesseract is a subprocess
    so it releases the GIL during the actual recognition work, and a 2-vCPU
    VPS comfortably handles 4 concurrent tesseract instances. Cuts a typical
    18-page extract from ~18 min (serial) to ~5 min (4-way parallel).
    """
    from concurrent.futures import ThreadPoolExecutor

    doc = fitz.open(pdf_path)
    n = len(doc)
    pages: list[Optional[str]] = [None] * n

    # First pass: pull text-layer pages directly, queue the rest for OCR.
    ocr_jobs: list[tuple[int, "fitz.Pixmap"]] = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if _looks_like_real_text(text):
            pages[i] = text
            print(f"  page {i+1}/{n}: text layer ({len(text)} chars)")
        else:
            # Render now (PyMuPDF is not thread-safe — keep all fitz calls
            # on the main thread; only the OCR step parallelises).
            ocr_jobs.append((i, page.get_pixmap(dpi=150)))
    doc.close()

    # Parallel OCR over the queued pixmaps. Order doesn't matter during
    # execution; we slot results back into ``pages[i]`` by index.
    if ocr_jobs:
        workers = max(1, min(ocr_workers, len(ocr_jobs)))
        print(f"  OCR'ing {len(ocr_jobs)} pages with {workers} parallel workers")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(ocr_page, pix): idx for idx, pix in ocr_jobs}
            done = 0
            from concurrent.futures import as_completed
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    text = fut.result()
                except Exception as exc:
                    text = ""
                    print(f"  page {idx+1}/{n}: OCR FAILED — {exc}")
                pages[idx] = text
                done += 1
                print(f"  page {idx+1}/{n}: OCR ({len(text)} chars)  [{done}/{len(ocr_jobs)} done]")

    return "\n\f\n".join(p or "" for p in pages)


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


# Bylines that mark "an article body starts here" in Indian newspapers. Keep
# these narrow (full-line matches only) — generic "two capitalised words"
# patterns over-fire on datelines like 'New Delhi' or section labels.
_BYLINE_PATTERNS = [
    re.compile(r"^\s*Express News Service\s*$", re.IGNORECASE),
    re.compile(r"^\s*(PRESS TRUST OF INDIA|PTI)\s*$"),
    re.compile(r"^\s*ANI\s*$"),
    re.compile(r"^\s*(Reuters|Bloomberg|Associated Press|AFP)\s*$", re.IGNORECASE),
    re.compile(r"^\s*FE Bureau\s*$"),
    re.compile(r"^\s*ENS Economic Bureau\s*$", re.IGNORECASE),
    re.compile(r"^\s*HT Correspondent\s*$", re.IGNORECASE),
    # 'By Jane Doe' / 'By A Correspondent' / 'By A.J. Smith' — allow
    # single-letter initials and 1-4 following words.
    re.compile(r"^\s*By\s+[A-Z][A-Za-z.]*(\s+[A-Z][A-Za-z.]*){0,4}\s*$"),
]


def _is_byline(line: str) -> bool:
    s = line.strip()
    if len(s) < 3 or len(s) > 60:
        return False
    return any(p.match(s) for p in _BYLINE_PATTERNS)


def _glue_hyphenated(text: str) -> str:
    """Tesseract breaks words at line-end with a soft hyphen ('gov-\\nernment').
    Glue them back so the LLM sees clean prose."""
    # Smart-hyphen (U+2010) and regular hyphen both appear
    return re.sub(r"(\w)[-‐‐]\n(\w)", r"\1\2", text)


def heuristic_segment(text: str) -> list[dict]:
    """Split OCR'd newspaper text into candidate articles by detecting bylines.

    A byline (e.g. 'Express News Service', 'PTI', 'By <Author>') reliably marks
    the start of an article body. Walk backward from each byline to find the
    headline (the closest non-empty lines above, before the next blank gap),
    forward to find the body (until the next byline or a hard cap).

    Returns a list of {"headline": str, "body": str} candidates. Empty list
    if no bylines found — caller should fall back to chunk-based classify.
    """
    text = _glue_hyphenated(text)
    lines = text.split("\n")
    byline_idx = [i for i, l in enumerate(lines) if _is_byline(l)]
    if not byline_idx:
        return []

    out: list[dict] = []
    for k, bidx in enumerate(byline_idx):
        # Headline = the closest non-empty lines above, before the first blank
        head_lines: list[str] = []
        for j in range(bidx - 1, max(-1, bidx - 12), -1):
            s = lines[j].strip()
            if not s:
                if head_lines:
                    break
                continue
            # Skip lines that are obviously not headlines (paragraph chunks)
            if len(s) > 200 or s.endswith("."):
                if head_lines:
                    break
                continue
            head_lines.insert(0, s)
        if not head_lines:
            continue
        headline = " ".join(head_lines).strip()
        if len(headline) < 8:
            continue

        # Body = lines after byline until next byline OR cap of 180 lines
        next_byline = byline_idx[k + 1] if k + 1 < len(byline_idx) else len(lines)
        end = min(next_byline, bidx + 180)
        body = "\n".join(lines[bidx + 1 : end]).strip()
        # Drop articles with too-short bodies — they're stubs / photo captions.
        # 150 chars ~ a 2-3 sentence news brief; below that is rarely a real
        # article.
        if len(body) < 150:
            continue
        out.append({"headline": headline, "body": body})
    return out


# Single-LLM-call batch classifier: send N candidates per call, get JSON back
# with only the UPSC-relevant ones structured. 4 candidates per batch keeps
# us comfortably under Groq's 6K-token per-request cap.
BATCH_CLASSIFY_SYSTEM = """You receive a list of newspaper article candidates. Each has a numeric idx, a headline, and a body.

For EACH candidate, decide if it's UPSC Civil Services exam-relevant.
- KEEP: editorials, op-eds, explainers, policy stories, court verdicts, treaties, scheme launches, report releases, investigations, foreign-policy news — anything touching GS-1 (history/geography/society/art-culture), GS-2 (polity/IR/social justice), GS-3 (economy/environment/S&T/security), GS-4 (ethics).
- DROP: ads, classifieds, sports, weather, market tickers, horoscopes, recipes, lifestyle fluff, page-fillers, anything that doesn't touch the syllabus.

For each KEEP, output one JSON object:
{
  "idx": <int — the candidate's idx as given>,
  "headline": "<clean headline>",
  "lede": "<first 2-3 sentences of the article>",
  "body": "<the article body, lightly normalised>",
  "paper": "GS-1 | GS-2 | GS-3 | GS-4 | essay",
  "static_topics": ["<2-4 syllabus tags like 'Polity/Federalism'>"],
  "static_link": "<one-line context tying the news to a static topic>"
}

Output ONLY a JSON array of the KEEP objects. No prose, no markdown fences.
Order by exam relevance (most useful first). If NONE are relevant, output [].
"""


def _format_candidates_for_llm(batch: list[dict], start_idx: int) -> str:
    """Render a batch of candidates as a numbered prompt for the LLM."""
    parts: list[str] = []
    for offset, c in enumerate(batch):
        idx = start_idx + offset
        # Cap body at 1500 chars so the prompt stays small; lede is enough for
        # the LLM to judge relevance.
        body = c["body"][:1500]
        parts.append(f"--- Candidate {idx} ---\nHeadline: {c['headline']}\n\n{body}")
    return "\n\n".join(parts)


def _classify_via_groq(candidates: list[dict], pool: list["Article"]) -> None:
    """Batched (4-at-a-time) Groq classify path. Used when claude_code isn't
    configured or its call fails."""
    BATCH = 4
    for start in range(0, len(candidates), BATCH):
        batch = candidates[start : start + BATCH]
        print(f"  batch classify {start+1}-{start+len(batch)}/{len(candidates)}")
        prompt = _format_candidates_for_llm(batch, start_idx=start)
        raw = _pipeline_chat(BATCH_CLASSIFY_SYSTEM, prompt,
                             max_tokens=2500, temperature=0.2)
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
        time.sleep(1.5)


def stage_classify(extracted_text: str, *, max_articles: int = 12) -> list[Article]:
    """Filter + structure articles into Article records, returning at most
    max_articles ordered by exam relevance.

    Strategy:
      1. Run ``heuristic_segment`` to find article boundaries from byline
         patterns. This typically returns 15-30 candidates for a 22-page
         newspaper — vs the ~100 chunks the old approach generated.
      2. Send candidates to the LLM in batches of 4 (small enough to fit
         under Groq's per-request 6K-token cap, large enough that we make
         only ~5-8 LLM calls per newspaper).
      3. If the heuristic returns fewer than 5 candidates (very rare —
         unusual paper format, OCR mangled all bylines), fall back to the
         old chunk-and-classify path.

    Expected LLM-call count per typical 22-page paper:
      - Old: ~98-148 calls
      - New: ~5-8 calls (15-25× reduction)
    """
    candidates = heuristic_segment(extracted_text)
    print(f"  heuristic_segment found {len(candidates)} candidate articles")

    pool: list[Article] = []

    if len(candidates) >= 5:
        # If claude_code is configured, do all candidates in ONE call (200K
        # context handles it easily). Otherwise batch 4-at-a-time through
        # Groq to fit under its 6K-token per-request cap.
        from bot.config import AUTHORING_PROVIDER
        if AUTHORING_PROVIDER == "claude_code":
            print(f"  classify backend: claude_code CLI (1 call, all {len(candidates)} candidates)")
            try:
                from bot.author import _author_claude_code
                prompt = _format_candidates_for_llm(candidates, start_idx=0)
                raw = _author_claude_code(BATCH_CLASSIFY_SYSTEM, prompt, max_tokens=8000)
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
            except Exception as exc:
                print(f"  classify via claude_code failed ({exc}); falling back to Groq batched")
                _classify_via_groq(candidates, pool)
        else:
            _classify_via_groq(candidates, pool)
    else:
        # Fallback: old chunk-and-classify approach. Used when the heuristic
        # can't find bylines (Hindu, ToI, vernacular layouts, OCR damage).
        print(f"  heuristic found <5 candidates; falling back to chunk path")
        chunks = _chunk_text(extracted_text, target_chars=4_500)
        chunks = [c for c in chunks if len(c.strip()) >= 400]
        for i, chunk in enumerate(chunks):
            print(f"  classify chunk {i+1}/{len(chunks)} ({len(chunk):,} chars)")
            raw = _pipeline_chat(CLASSIFY_SYSTEM, chunk,
                                 max_tokens=1500, temperature=0.2)
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
            time.sleep(1.5)
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
    """Author each article (mutates in place, filling ``markdown``).

    Prefers the Claude Code CLI when ``AUTHORING_PROVIDER=claude_code`` —
    bills against the user's Anthropic Max subscription instead of the
    Groq free-tier daily token quota the OCR + classify stages already
    drain. Falls back to Groq on per-call exception, or permanently to
    Groq if Claude CLI surfaces an auth-style unrecoverable failure.
    """
    from bot.author import _author_claude_code, ClaudeCodeUnrecoverableError
    from bot.config import AUTHORING_PROVIDER

    use_claude = AUTHORING_PROVIDER == "claude_code"
    if use_claude:
        print(f"  author backend: claude_code CLI (Anthropic Max subscription)")
    else:
        print(f"  author backend: groq {PIPELINE_LLM}")

    for i, art in enumerate(articles):
        n = start_num + i
        print(f"  authoring {n}/{start_num + len(articles) - 1}: {art.headline[:60]!r}")
        # Pull PYQs from the verified corpus
        art.pyqs = find_pyqs(art.static_topics, limit=3)
        prompt = _format_author_prompt(art, n)

        if use_claude:
            try:
                raw = _author_claude_code(AUTHOR_SYSTEM, prompt, max_tokens=4000)
            except ClaudeCodeUnrecoverableError as exc:
                # OAuth dead or rate window stuck — fall back to Groq for the
                # rest of the run, logged so admin sees the swap.
                print(f"    claude_code unrecoverable ({exc}); falling back to Groq for remaining articles")
                use_claude = False
                raw = _pipeline_chat(AUTHOR_SYSTEM, prompt, max_tokens=1500, temperature=0.3)
            except Exception as exc:
                # Transient Claude CLI failure — fall back THIS article only,
                # keep trying Claude on the next one.
                print(f"    claude_code attempt failed ({exc}); using Groq for this article only")
                raw = _pipeline_chat(AUTHOR_SYSTEM, prompt, max_tokens=1500, temperature=0.3)
        else:
            raw = _pipeline_chat(AUTHOR_SYSTEM, prompt, max_tokens=1500, temperature=0.3)

        art.markdown = raw.strip()
        time.sleep(0.5)


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
    B.COVER_FOOTER = "Curated for UPSC Civil Services aspirants - cheetsheet.tech/upsc"

    issue_url = f"https://cheetsheet.tech/upsc/{issue_date.isoformat()}"
    B.build(
        src=md_path,
        out=out_path,
        title=title,
        subtitle=f"{source} - {issue_date.strftime('%-d %B %Y') if sys.platform != 'win32' else issue_date.strftime('%#d %B %Y')}",
        # `qr` (not `chapters`) — the chapter-index page duplicates the
        # digest's own intro + Must-read-three callout. We still want the
        # cover QR.
        features=["summary", "tldr", "qna", "qr"],
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
    parts.append("\n*Generated by Cheetsheet UPSC Daily — cheetsheet.tech/upsc*")
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
        _set_status(issue_id, status="classifying", extract_seconds=extract_dt)
        print(f"[upsc] {issue_id} stage 2: classify")
        t0 = time.monotonic()
        articles = stage_classify(raw_text, max_articles=12)
        classify_dt = time.monotonic() - t0
        print(f"  -> classify took {classify_dt:.1f}s")
        if not articles:
            raise RuntimeError("classify produced 0 articles — bad extraction?")
        print(f"  -> {len(articles)} articles survived classification")

        # ------------------------------------------------------------------ author
        _set_status(issue_id, status="authoring", classify_seconds=classify_dt)
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
