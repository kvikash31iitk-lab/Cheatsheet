#!/usr/bin/env python3
"""Seed the ``pyq`` table from UPSC previous-year papers hosted on drishtiias.com.

The UPSC Cheetsheet authoring pipeline cites PYQs from this table — never from
LLM imagination. So the integrity of this seed is load-bearing: every row that
lands here is something the renderer is allowed to cite in a published digest.

Pipeline per PDF:
  1. Download (cached under ``.upsc_work/pyq_cache/``)
  2. Extract text with PyMuPDF
  3. Ask Groq Llama to structure the text into JSON questions
  4. Ask Groq Llama to tag each question with 1-3 syllabus topics
  5. Upsert into ``pyq`` (idempotent on ``(year, paper, question_num)``)

Usage:
  # Smoke test: one Prelims paper end-to-end
  python scripts/seed_pyq_corpus.py --years 2024 --stages prelims

  # Full Prelims archive (12 papers, 2013-2025)
  python scripts/seed_pyq_corpus.py --years 2013-2025 --stages prelims

  # Mains 2024 (5 papers: GS-1..GS-4 + Essay)
  python scripts/seed_pyq_corpus.py --years 2024 --stages mains

  # Re-tag rows already in DB (no scraping, no parsing — just tags)
  python scripts/seed_pyq_corpus.py --retag-only

  # Process local PDFs from disk (manual override for missing years)
  python scripts/seed_pyq_corpus.py --local-dir .upsc_work/pyq_pdfs

  # Limit how many PDFs to process this run
  python scripts/seed_pyq_corpus.py --years 2013-2025 --stages prelims --limit 2
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import fitz  # PyMuPDF
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from api.db import SyncSessionLocal, Base, sync_engine  # noqa: E402
from api import models  # noqa: E402  -- registers all tables
from api.models import Pyq  # noqa: E402
from bot.config import GROQ_API_KEY, AUTHORING_MODEL  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "web_work" / "upsc_pyq_cache"
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # Importing this module shouldn't fail just because we can't pre-create
    # the cache dir. The CLI / pipeline will surface a clearer error later
    # when it actually tries to write a PDF. On a botuser-owned web_work/
    # this should never trigger.
    pass

USER_AGENT = "CheetsheetUPSC/1.0 (+https://cheetsheet.tech) - caching scraper"


# =============================================================================
# URL discovery — Drishti
# =============================================================================
# Hardcoded list of (year, exam_stage, paper, url) tuples. These were captured
# from drishtiias.com's free-downloads pages on 2026-06-01. Drishti keeps file
# names stable for years; if URLs rot we'll catch it as a download error and
# update this table.

PRELIMS_URLS: dict[int, str] = {
    # Prelims GS Paper I (the 100-MCQ paper that's the heart of UPSC)
    2026: "https://www.drishtiias.com/images/pdf/GS Series D- English.pdf",
    2025: "https://www.drishtiias.com/images/pdf/GS English Set-B.pdf",
    2024: "https://www.drishtiias.com/images/pdf/1718537625_upsc-pre-2024-GS-(B).pdf",
    2023: "https://www.drishtiias.com/images/pdf/UPSC 2023 Questions English.pdf",
    2022: "https://www.drishtiias.com/images/pdf/GS Paper 2022 (English) with logo.pdf",
    2021: "https://www.drishtiias.com/images/pdf/New doc Oct 10, 2021 11.35 (English ).pdf",
    2020: "https://www.drishtiias.com/images/pdf/UPSC_Prelims_Exam_2020_GS_Paper_I.pdf.pdf",
    2019: "https://www.drishtiias.com/images/pdf/Prelims Question Paper-I 2019.pdf",
    2018: "https://www.drishtiias.com/images/pdf/gs2018.pdf",
    2017: "https://www.drishtiias.com/images/pdf/GS2017.pdf",
    2016: "https://www.drishtiias.com/images/pdf/GS2016.pdf",
    2015: "https://www.drishtiias.com/images/pdf/GS2015.pdf",
    2014: "https://www.drishtiias.com/images/pdf/gs2014.pdf",
    2013: "https://www.drishtiias.com/images/pdf/gs2013.pdf",
}

# Mains: each year is a sub-page on Drishti with 5 PDFs (GS-1..4 + Essay).
# We've seeded 2024 from a manual fetch; the rest are discovered lazily by
# scraping the per-year landing page.
MAINS_URLS: dict[int, dict[str, str]] = {
    2024: {
        "GS-1":   "https://www.drishtiias.com/images/pdf/UPSC Mains 2024 GS Paper I...pdf",
        "GS-2":   "https://www.drishtiias.com/images/pdf/02 UPSC 2024 Paper-II.pdf",
        "GS-3":   "https://www.drishtiias.com/images/pdf/03 UPSC 2024 Paper-III.pdf",
        "GS-4":   "https://www.drishtiias.com/images/pdf/05 UPSC 2024 Paper-IV_Final 1.pdf",
        "essay":  "https://www.drishtiias.com/images/pdf/UPSC Mains 2024 Essay Paper...pdf",
    },
}


def discover_mains_year(year: int) -> dict[str, str]:
    """Scrape Drishti's per-year Mains page to find the 5 paper URLs.

    Returns a {paper_label: pdf_url} dict, where paper_label is one of
    "GS-1", "GS-2", "GS-3", "GS-4", "essay". Falls back to MAINS_URLS[year]
    if scraping fails or yields nothing.
    """
    if year in MAINS_URLS:
        return MAINS_URLS[year]
    landing = f"https://www.drishtiias.com/free-downloads/previous-year-papers-mains-papers-by-year-{year}"
    try:
        html = _http_get_text(landing)
    except Exception as exc:
        print(f"  WARN: could not fetch {landing}: {exc}", file=sys.stderr)
        return {}
    out: dict[str, str] = {}
    for match in re.finditer(r'href="(/images/pdf/[^"]+\.pdf)"', html, re.IGNORECASE):
        url = "https://www.drishtiias.com" + match.group(1)
        label = _classify_mains_url(url)
        if label and label not in out:
            out[label] = url
    return out


def _classify_mains_url(url: str) -> Optional[str]:
    """Guess the paper label from a Mains PDF URL. Heuristic; verified by the
    LLM extraction step downstream so a wrong guess here is recoverable."""
    u = url.lower()
    if "essay" in u:
        return "essay"
    if "paper-i " in u or "paper i" in u or "paper-1" in u or " gs paper i" in u or " gs-1" in u or "paper-i." in u:
        return "GS-1"
    if "paper-ii" in u or "paper ii" in u or "paper-2" in u or " gs-2" in u:
        return "GS-2"
    if "paper-iii" in u or "paper iii" in u or "paper-3" in u or " gs-3" in u:
        return "GS-3"
    if "paper-iv" in u or "paper iv" in u or "paper-4" in u or " gs-4" in u:
        return "GS-4"
    return None


# =============================================================================
# HTTP + caching
# =============================================================================

def _http_get_text(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r.text


def download_pdf(url: str) -> Path:
    """Download a PDF if not already cached. Returns local path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = re.sub(r"[^A-Za-z0-9._-]+", "_", url.rsplit("/", 1)[-1])
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    dest = CACHE_DIR / fname
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    print(f"  downloading {url}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, stream=True)
    r.raise_for_status()
    with dest.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            fh.write(chunk)
    return dest


# =============================================================================
# PDF -> text (with OCR fallback for scanned Drishti PDFs)
# =============================================================================

OCR_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
OCR_DPI = 150  # 150 dpi A4 = ~1240x1754, safely under Groq's image size cap


def _wait_for_429(exc: Exception, *, default_wait: float) -> float:
    """Parse Groq's 'Please try again in X.Xs' hint and return seconds to wait.

    The Groq SDK surfaces 429 as a string in the message; parse defensively
    and fall back to ``default_wait`` if the hint is missing.
    """
    import re
    msg = str(exc)
    m = re.search(r"try again in ([\d.]+)\s*s", msg, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) + 0.5  # tiny buffer
        except ValueError:
            pass
    return default_wait


def ocr_page(pix) -> str:
    """OCR a single rendered PDF page via Groq Llama 4 Scout (vision).

    Retries 6 times. On 429s, parses the 'try again in Xs' hint and waits
    that long. On other errors, exponential backoff.
    """
    import base64
    from groq import Groq
    b64 = base64.b64encode(pix.tobytes("png")).decode()
    client = Groq(api_key=GROQ_API_KEY)
    last_err: Optional[Exception] = None
    for attempt in range(1, 7):
        try:
            resp = client.chat.completions.create(
                model=OCR_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text":
                            "Extract every word of text from this UPSC exam page exactly as it appears. "
                            "Preserve question numbers, option letters (a), (b), (c), (d), and the order of items. "
                            "Output ONLY the text content — no preamble, no commentary, no markdown formatting."},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
                temperature=0.0,
                max_tokens=4000,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            last_err = exc
            wait = _wait_for_429(exc, default_wait=5 * attempt)
            print(f"      OCR attempt {attempt}/6 failed: waiting {wait:.1f}s — {str(exc)[:140]}")
            time.sleep(wait)
    raise RuntimeError(f"OCR failed after 6 attempts: {last_err}")


def extract_text(pdf_path: Path, *, ocr_threshold: int = 100,
                 max_pages: Optional[int] = None) -> str:
    """Pull plain text from every page. OCR fallback for image-only pages.

    UPSC papers on Drishti are uniformly scanned images with no extractable
    text layer, so in practice every page goes through the vision model.
    """
    doc = fitz.open(pdf_path)
    pages: list[str] = []
    n_pages = len(doc) if max_pages is None else min(len(doc), max_pages)
    for i in range(n_pages):
        page = doc[i]
        text = page.get_text("text").strip()
        if len(text) < ocr_threshold:
            pix = page.get_pixmap(dpi=OCR_DPI)
            text = ocr_page(pix)
            print(f"      OCR page {i+1}/{n_pages}: {len(text)} chars")
        else:
            print(f"      text page {i+1}/{n_pages}: {len(text)} chars")
        pages.append(text)
    doc.close()
    return "\n\f\n".join(pages)


# =============================================================================
# Groq calls
# =============================================================================

def _groq_chat(system: str, user: str, *, max_tokens: int = 8000,
               temperature: float = 0.1) -> str:
    """Single Groq Llama call. Retries 6x; honours 'try again in Xs' on 429."""
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    last_err: Optional[Exception] = None
    for attempt in range(1, 7):
        try:
            resp = client.chat.completions.create(
                model=AUTHORING_MODEL,
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
            print(f"    groq attempt {attempt}/6 failed: waiting {wait:.1f}s — {str(exc)[:140]}")
            time.sleep(wait)
    raise RuntimeError(f"Groq failed after 6 attempts: {last_err}")


EXTRACT_SYSTEM_PRELIMS = """You receive OCR-extracted text from a UPSC Prelims General Studies Paper-I.

UPSC Prelims papers are BILINGUAL — every question appears twice on the same page,
once in Hindi (Devanagari script) and once in English. Extract ONLY the English
versions. Skip Hindi text, instructions, headers, footers, and answer keys.

Return a JSON array of question objects with this shape:

{
  "num": <int — the question number printed on the paper>,
  "text": "<English question stem, options excluded>",
  "options": ["<option (a)>", "<option (b)>", "<option (c)>", "<option (d)>"]
}

Rules:
- Output ONLY a JSON array. No prose, no markdown fences.
- Skip any question where the English version is incomplete or garbled.
- Preserve the original wording — do not rephrase or summarize.
- Question numbers should be 1-100 (a Prelims GS paper has 100 MCQs).
- The English version often appears below the Hindi one or on the next page;
  match them up by sequential order.
"""

EXTRACT_SYSTEM_MAINS = """You receive raw text extracted from a UPSC Mains General Studies / Essay paper PDF.

Your job: return a JSON array of every question on the paper. Skip headers,
footers, and instructions. Each question has the shape:

{
  "num": <int, the 1-based question number on the paper>,
  "text": "<the full question stem>",
  "marks": <int, marks for the question — usually 10 or 15 for GS, 125 or 250 for Essay>
}

Rules:
- Output ONLY a JSON array. No prose, no markdown fences.
- Preserve original wording.
- Pull marks from the bracketed annotation at the end of each question
  (e.g. "(10 marks)" or "(150 words / 10 marks)").
- Number questions in the order they appear in the paper.
"""

TAG_SYSTEM = """You tag UPSC exam questions with 1-3 syllabus topics from this list:

Polity & Governance: Constitution, Fundamental Rights, DPSP, Parliament, Judiciary, Executive, Federalism, Local Govt, Elections, Constitutional Bodies, Statutory Bodies, RTI, Public Service
History: Ancient India, Medieval India, Modern India, Indian National Movement, Post-Independence, World History, Art & Culture
Geography: Physical Geography India, Physical Geography World, Human Geography, Economic Geography, Mapping, Disaster Management
Society: Indian Society, Diversity, Women & Gender, Population, Urbanisation, Globalisation, Communalism, Secularism
International Relations: India & Neighbours, India & World, Bilateral, Regional Groupings, International Organisations, Diaspora, Global Treaties
Economy: Indian Economy, Growth & Development, Agriculture, Industry, Infrastructure, Investment Models, Inclusive Growth, Budget, Banking, External Sector, GST
Internal Security: Linkages of Development & Security, Cybersecurity, Money Laundering, Border Management, Terrorism, Defence Forces
Environment: Conservation, Biodiversity, Climate Change, Pollution, EIA, Renewable Energy, Sustainability
Science & Tech: Space, Biotech, IT, Nanotech, Indigenisation, Awareness, IP Rights, Health
Ethics: Ethics & Human Interface, Attitude, Aptitude, Emotional Intelligence, Moral Thinkers, Public Service Values, Corporate Governance, Case Studies

Output ONLY a JSON object mapping question_num -> list_of_topics. Example:
  {"1": ["Polity & Governance/Constitution"], "2": ["History/Modern India", "History/Indian National Movement"]}

Topics MUST come from the list above; do not invent new tags. Use 'Heading/Subtopic' format.
"""


@dataclass
class ParsedQuestion:
    num: int
    text: str
    marks: Optional[int] = None
    options: Optional[list[str]] = None
    static_topics: Optional[list[str]] = None


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _strip_devanagari_lines(text: str, hindi_ratio_threshold: float = 0.20) -> str:
    """Drop lines that are >20% Devanagari characters.

    UPSC Prelims papers print every question twice (Hindi then English). The
    8b-instant model tends to mistranslate Hindi-only chunks instead of
    skipping them, producing duplicate-but-wrong questions. Stripping Hindi
    lines pre-LLM is more reliable than instructing the model to skip them.
    """
    out_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        non_ws = len(stripped)
        devanagari_count = len(_DEVANAGARI.findall(stripped))
        if non_ws > 0 and devanagari_count / non_ws > hindi_ratio_threshold:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def extract_questions(text: str, exam_stage: str) -> list[ParsedQuestion]:
    """Use Groq to structure the raw text into question records.

    Chunked tight (4000 chars/chunk) to fit under the free-tier TPM limit
    on ``llama-3.1-8b-instant`` (6000 TPM). max_tokens is also kept modest
    (2500) since each chunk produces only a handful of questions.

    Hindi (Devanagari) lines are stripped pre-LLM since the small model
    tends to translate them instead of skipping, producing duplicate-but-
    wrong questions.
    """
    system = EXTRACT_SYSTEM_PRELIMS if exam_stage == "prelims" else EXTRACT_SYSTEM_MAINS
    text = _strip_devanagari_lines(text)
    chunks = _split_text_for_extraction(text, target_chars=4000)
    out: list[ParsedQuestion] = []
    for i, chunk in enumerate(chunks):
        print(f"    extracting chunk {i+1}/{len(chunks)} ({len(chunk):,} chars)")
        raw = _groq_chat(system, chunk, max_tokens=2500)
        rows = _safe_json_array(raw)
        for r in rows:
            try:
                out.append(ParsedQuestion(
                    num=int(r["num"]),
                    text=str(r["text"]).strip(),
                    marks=int(r["marks"]) if "marks" in r and r["marks"] is not None else None,
                    options=[str(o).strip() for o in r["options"]] if "options" in r and r["options"] else None,
                ))
            except (KeyError, ValueError, TypeError):
                continue
        # Polite pacing so we don't burst the TPM cap on the free tier.
        time.sleep(1.0)
    return out


def tag_questions(questions: list[ParsedQuestion]) -> None:
    """Mutate questions in place, filling in static_topics via Groq. Batched."""
    BATCH = 15
    for start in range(0, len(questions), BATCH):
        batch = questions[start:start + BATCH]
        prompt = "\n\n".join(f"Q{q.num}: {q.text}" for q in batch)
        print(f"    tagging questions {start+1}..{start+len(batch)} / {len(questions)}")
        raw = _groq_chat(TAG_SYSTEM, prompt, max_tokens=2000, temperature=0.0)
        try:
            mapping = json.loads(_strip_fence(raw))
        except json.JSONDecodeError:
            print(f"      WARN: tag response was not valid JSON, skipping batch")
            continue
        for q in batch:
            topics = mapping.get(str(q.num)) or mapping.get(q.num)
            if isinstance(topics, list):
                q.static_topics = [str(t) for t in topics][:3]


def _split_text_for_extraction(text: str, target_chars: int = 25_000) -> list[str]:
    if len(text) <= target_chars:
        return [text]
    parts = text.split("\f")
    # Greedy pack pages until we hit target
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for p in parts:
        if size + len(p) > target_chars and buf:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(p)
        size += len(p)
    if buf:
        out.append("\n".join(buf))
    return out


def _strip_fence(s: str) -> str:
    """Strip ```json ... ``` fences if the model added them."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _safe_json_array(raw: str) -> list[dict]:
    text = _strip_fence(raw)
    # Try strict parse first
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        pass
    # Last-ditch: find the first [...] block and try again
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


# =============================================================================
# DB upsert
# =============================================================================

def upsert_pyqs(
    year: int,
    exam_stage: str,
    paper: str,
    source_url: str,
    questions: list[ParsedQuestion],
) -> tuple[int, int]:
    """Insert or update rows in the pyq table. Returns (inserted, updated)."""
    inserted = updated = 0
    with SyncSessionLocal() as session:
        for q in questions:
            existing = session.execute(
                select(Pyq).where(
                    Pyq.year == year,
                    Pyq.paper == paper,
                    Pyq.question_num == q.num,
                )
            ).scalar_one_or_none()
            topics_json = json.dumps(q.static_topics) if q.static_topics else None
            if existing is None:
                session.add(Pyq(
                    year=year,
                    exam_stage=exam_stage,
                    paper=paper,
                    section=None,
                    question_num=q.num,
                    question_text=q.text,
                    marks=q.marks,
                    static_topics=topics_json,
                    source_url=source_url,
                ))
                inserted += 1
            else:
                # Refresh fields that might have improved (text cleanup, tags)
                existing.question_text = q.text
                if q.marks is not None:
                    existing.marks = q.marks
                if topics_json is not None:
                    existing.static_topics = topics_json
                updated += 1
        session.commit()
    return inserted, updated


# =============================================================================
# Pipeline orchestration
# =============================================================================

def process_pdf(
    *,
    pdf_path: Path,
    year: int,
    exam_stage: str,
    paper: str,
    source_url: str,
    do_tag: bool = True,
) -> None:
    print(f"  -> {paper} {year} ({exam_stage}) from {pdf_path.name}")
    raw_text = extract_text(pdf_path)
    if len(raw_text.strip()) < 500:
        print(f"     WARN: extracted text suspiciously short ({len(raw_text)} chars). Skipping.")
        return
    questions = extract_questions(raw_text, exam_stage)
    print(f"     parsed {len(questions)} questions")
    if do_tag and questions:
        tag_questions(questions)
    inserted, updated = upsert_pyqs(year, exam_stage, paper, source_url, questions)
    print(f"     DB: +{inserted} new, ~{updated} updated")


def parse_year_range(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", default="2024",
                    help="Single year (2024) or range (2013-2025). Default: 2024.")
    ap.add_argument("--stages", nargs="+", default=["prelims"],
                    choices=["prelims", "mains"],
                    help="Which exam stages to seed. Default: prelims.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap the total number of PDFs processed this run "
                         "(0 = no cap). Useful for smoke tests.")
    ap.add_argument("--no-tag", action="store_true",
                    help="Skip the LLM tagging step. Faster smoke test; tags "
                         "can be filled in later with --retag-only.")
    ap.add_argument("--retag-only", action="store_true",
                    help="Skip downloading + parsing. Just re-run LLM tagging "
                         "on every row already in the pyq table.")
    ap.add_argument("--local-dir", type=Path, default=None,
                    help="Process PDFs from this folder instead of Drishti. "
                         "File names should follow the pattern "
                         "'<year>_<stage>_<paper>.pdf', e.g. '2024_mains_GS-2.pdf'.")
    args = ap.parse_args()

    # Make sure the schema exists before we try to write.
    Base.metadata.create_all(sync_engine)

    if not GROQ_API_KEY and not args.no_tag and not args.retag_only:
        sys.exit("ERROR: GROQ_API_KEY missing in .env (needed for question "
                 "extraction). Either set it or pass --no-tag.")

    if args.retag_only:
        retag_all()
        return

    targets: list[tuple[int, str, str, str]] = []  # (year, stage, paper, url)
    if args.local_dir:
        for pdf in sorted(args.local_dir.glob("*.pdf")):
            m = re.match(r"(\d{4})_(prelims|mains)_(.+)\.pdf$", pdf.name, re.IGNORECASE)
            if not m:
                print(f"  WARN: skipping {pdf.name} (name doesn't match year_stage_paper.pdf)")
                continue
            year, stage, paper = int(m.group(1)), m.group(2).lower(), m.group(3)
            targets.append((year, stage, paper, f"file://{pdf}"))
    else:
        years = parse_year_range(args.years)
        for year in years:
            if "prelims" in args.stages and year in PRELIMS_URLS:
                targets.append((year, "prelims", "GS-1", PRELIMS_URLS[year]))
            if "mains" in args.stages:
                mains = discover_mains_year(year)
                for paper, url in mains.items():
                    targets.append((year, "mains", paper, url))

    if args.limit > 0:
        targets = targets[:args.limit]

    if not targets:
        print("No matching PDFs found. Check --years / --stages / URL maps.")
        return

    print(f"Processing {len(targets)} PDFs:")
    for (year, stage, paper, url) in targets:
        print(f"  - {year} {stage} {paper}: {url}")

    for (year, stage, paper, url) in targets:
        try:
            if url.startswith("file://"):
                pdf_path = Path(url[7:])
            else:
                pdf_path = download_pdf(url)
            process_pdf(
                pdf_path=pdf_path,
                year=year,
                exam_stage=stage,
                paper=paper,
                source_url=url,
                do_tag=not args.no_tag,
            )
        except Exception as exc:
            print(f"  ERROR processing {year} {paper}: {exc}")
            continue


def retag_all() -> None:
    """Re-run the LLM tagging step on every row already in the pyq table."""
    with SyncSessionLocal() as session:
        rows = session.execute(select(Pyq).order_by(Pyq.year, Pyq.paper, Pyq.question_num)).scalars().all()
        print(f"Re-tagging {len(rows)} rows")
        # Group by (year, paper) so tag_questions can batch sensibly
        from collections import defaultdict
        buckets: dict[tuple[int, str], list[Pyq]] = defaultdict(list)
        for r in rows:
            buckets[(r.year, r.paper)].append(r)
        for (year, paper), batch in buckets.items():
            print(f"  {year} {paper}: {len(batch)} questions")
            pq = [ParsedQuestion(num=r.question_num or 0, text=r.question_text, marks=r.marks) for r in batch]
            tag_questions(pq)
            for r, q in zip(batch, pq):
                if q.static_topics:
                    r.static_topics = json.dumps(q.static_topics)
        session.commit()


if __name__ == "__main__":
    main()
