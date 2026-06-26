#!/usr/bin/env python3
"""Spoken-rewrite stage for the UPSC video pipeline.

Takes an issue's already-authored digest markdown (``UpscIssue.markdown`` — the
v2 schema with tables, MCQ-option labels, Obsidian callouts and PYQ codes) and
turns each article into *flowing, TTS-ready spoken prose*. The output is the
narration script the video engine (``scripts.upsc_video``) feeds to the TTS
backend, one section per article.

This module owns ONLY the script generation. It reuses
``scripts.upsc_pipeline._pipeline_chat`` (the Groq call already pinned to
``llama-3.1-8b-instant`` with 429-hint backoff) with a NEW spoken-rewrite
system prompt — it does not modify ``upsc_pipeline``.

Public contract (per the shared build spec):

    generate_script(issue_id) -> list[{
        "section_id": str,    # stable id for the section, e.g. "intro" / "art-01"
        "label":      str,    # short human label shown in the UI
        "text":       str,    # the spoken narration prose for this section
        "est_seconds": float, # rough duration estimate (words / 2.5)
    }]

The list always begins with an ``intro`` section and ends with an ``outro``
section; in between is one section per authored article.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.db import SyncSessionLocal  # noqa: E402
from api.models import UpscIssue  # noqa: E402

# Reuse the pipeline's Groq helper. We DO NOT edit upsc_pipeline; we only call
# its already-tested chat function with our own system prompt.
from scripts.upsc_pipeline import _pipeline_chat  # noqa: E402


# Speaking-rate constant. UPSC explainer narration in Hindi/Hinglish lands
# around 2.5 words/second once natural pauses are included; the UI uses the
# same figure so the estimate it shows matches what we compute here.
WORDS_PER_SECOND = 2.5


SPOKEN_REWRITE_SYSTEM = """You rewrite ONE article from a UPSC daily-digest study sheet into spoken narration for a voiceover video.

You will be given the article's markdown. It contains study-sheet scaffolding —
markdown tables, headings, Obsidian callouts (lines starting with "> [!...]"),
multiple-choice option labels like "(a)", "(b)", bolded field labels, and
past-year-question reference codes. None of that can be read aloud as-is.

Convert it into clear, flowing spoken prose that an Indian UPSC teacher would
say while explaining this story to aspirants. Rules:

- Output ONLY the narration text. No markdown, no headings, no bullet points,
  no callout markers, no tables, no asterisks, no "(a)/(b)/(c)/(d)" option
  labels, no "PYQ" codes, no exam-paper codes like "GS-2 2019 (15M)".
- Write in complete sentences and natural paragraphs. It must sound like a
  person talking, not a sheet being read out.
- Lead with the news hook ("why this is in the news"), then the few key facts
  an answer must carry, then the balanced for/against/way-forward analysis,
  then why it matters for the exam — but weave these together as connected
  speech, do NOT announce the section names.
- Drop the prelims/mains practice questions and the PYQ-link list entirely;
  instead, in one short sentence, mention which broad syllabus area this topic
  connects to, if it is clear from the article.
- Keep numbers, names, dates and places EXACTLY as written in the source.
- Target roughly 45 to 90 seconds of speech for this article — about 120 to
  230 spoken words. Be tight; do not pad.
"""

# The digest markdown is English; the narration LANGUAGE is chosen by the user
# (default Hindi). The article rewrite must output in that language, NOT the
# source language — otherwise intro/outro (Hindi) and articles (English) mix.
_LANG_DIRECTIVE = {
    "hi": (
        "OUTPUT LANGUAGE — write the entire narration in HINDI, as natural Hinglish in "
        "Devanagari script, in the warm voice of an Indian UPSC teacher. Keep proper nouns "
        "(people, places, organisations) and established English terms readable, "
        "transliterating them into Devanagari where natural (e.g. ट्रांसशिपमेंट पोर्ट, करंट "
        "अकाउंट सरप्लस). Spell numbers, money and acronyms out in Hindi words (इक्यासी हज़ार "
        "करोड़ रुपये, जीडीपी, यूपीएससी). Write ONLY in Hindi/Devanagari — do NOT write the "
        "narration in English."
    ),
    "en": "OUTPUT LANGUAGE — write the entire narration in clear, natural English.",
}


# =============================================================================
# Markdown -> per-article splitting
# =============================================================================

# Articles in the authored digest start with a level-2 heading "## N. Headline".
# The digest preamble (# UPSC Daily Digest, the must-read-three callout) sits
# above the first "## " and the Annexure sits after the last article — both are
# scaffolding we don't narrate verbatim.
_ARTICLE_HEAD = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)


def _split_articles(markdown: str) -> list[tuple[str, str]]:
    """Split authored digest markdown into ``(headline, body_md)`` per article.

    Returns the list in document order. The preamble before the first article
    and the trailing Annexure section are excluded.
    """
    heads = list(_ARTICLE_HEAD.finditer(markdown))
    if not heads:
        return []
    out: list[tuple[str, str]] = []
    for i, m in enumerate(heads):
        headline = m.group(2).strip()
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(markdown)
        body = markdown[start:end].strip()
        # Trim a trailing Annexure that landed inside the last article block.
        ann = re.search(r"^##\s+Annexure\b", body, re.MULTILINE)
        if ann:
            body = body[: ann.start()].strip()
        if headline:
            out.append((headline, body))
    return out


def _strip_for_fallback(headline: str, body_md: str) -> str:
    """Deterministic markdown->prose cleanup, used only when the LLM rewrite
    fails so the section still has *some* readable narration rather than None.

    Drops tables, callout markers, option labels, PYQ codes and markdown
    emphasis. Not as fluent as the LLM pass, but safe and offline.
    """
    lines: list[str] = []
    for raw in body_md.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("|"):  # table row
            continue
        if s.startswith("#"):  # sub-heading
            continue
        if re.match(r"^>\s*\[!", s):  # callout opener "> [!tldr] ..."
            s = re.sub(r"^>\s*\[![^\]]*\]\s*", "", s)
        s = re.sub(r"^>\s*", "", s)          # quote markers
        s = re.sub(r"^[-*]\s+", "", s)       # bullets
        s = re.sub(r"^\d+\.\s+", "", s)      # ordered list "1. "
        s = re.sub(r"\([a-d]\)", "", s)       # MCQ option labels
        s = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", s)  # bold/italic
        s = re.sub(r"`([^`]+)`", r"\1", s)    # inline code
        s = s.strip()
        if s:
            lines.append(s)
    text = " ".join(lines)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return f"{headline}. {text}" if text else headline


def est_seconds(text: str) -> float:
    """Rough spoken-duration estimate: words / WORDS_PER_SECOND."""
    words = len(re.findall(r"\S+", text or ""))
    return round(words / WORDS_PER_SECOND, 1) if words else 0.0


# =============================================================================
# Intro / outro
# =============================================================================

def _intro_text(source: str, date_str: str, count: int, lang: str) -> str:
    if lang == "hi":
        return (
            f"नमस्ते दोस्तों, स्वागत है आपका यू पी एस सी डेली डाइजेस्ट में। "
            f"आज हम {source} के {date_str} के अंक से {count} परीक्षा के लिहाज़ से "
            f"सबसे ज़रूरी ख़बरों को सरल भाषा में समझेंगे। तो चलिए शुरू करते हैं।"
        )
    return (
        f"Hello and welcome to today's UPSC daily digest. "
        f"In this video we'll break down the {count} most exam-relevant stories "
        f"from {source}, dated {date_str}, in clear and simple terms. "
        f"Let's get started."
    )


def _outro_text(lang: str) -> str:
    if lang == "hi":
        return (
            "तो दोस्तों, ये थीं आज की सबसे अहम ख़बरें। अगर ये डाइजेस्ट उपयोगी "
            "लगा हो तो चैनल को सब्सक्राइब ज़रूर करें, और कल फिर मिलते हैं एक "
            "नए डाइजेस्ट के साथ। धन्यवाद।"
        )
    return (
        "And that's a wrap on today's most important stories. If you found this "
        "digest useful, do subscribe to the channel, and we'll see you tomorrow "
        "with a fresh digest. Thank you."
    )


# =============================================================================
# Public API
# =============================================================================

def rewrite_article(headline: str, body_md: str, lang: str = "hi") -> str:
    """LLM spoken-rewrite of one article in the target ``lang``. Falls back to a
    deterministic strip if the LLM call fails so the caller always gets prose."""
    system = SPOKEN_REWRITE_SYSTEM + "\n" + _LANG_DIRECTIVE.get(lang, _LANG_DIRECTIVE["hi"])
    prompt = f"Headline: {headline}\n\n=== Article markdown ===\n{body_md}\n"
    try:
        raw = _pipeline_chat(system, prompt,
                             max_tokens=900, temperature=0.4)
        text = (raw or "").strip()
        # Belt-and-braces: strip any stray markdown the model leaked through.
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", text)
        text = re.sub(r"^[>\-*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{2,}", " ", text).strip()
        if len(text) >= 40:
            return text
    except Exception as exc:  # noqa: BLE001
        print(f"  spoken-rewrite LLM failed for {headline[:50]!r}: {exc}", flush=True)
    return _strip_for_fallback(headline, body_md)


def generate_script(issue_id: str, *, lang: str = "hi") -> list[dict]:
    """Build the narration script for an issue from its authored markdown.

    Returns ``list[{section_id, label, text, est_seconds}]`` with an intro
    first, one section per authored article, and an outro last. Raises
    ``RuntimeError`` if the issue has no authored markdown yet.
    """
    with SyncSessionLocal() as session:
        row = session.get(UpscIssue, issue_id)
        if row is None:
            raise RuntimeError(f"UpscIssue {issue_id} not found")
        markdown: Optional[str] = row.markdown
        source = row.source or "the newspaper"
        try:
            date_str = row.issue_date.strftime("%d %B %Y").lstrip("0")
        except Exception:  # noqa: BLE001
            date_str = str(getattr(row, "issue_date", ""))

    if not markdown or not markdown.strip():
        raise RuntimeError(
            f"UpscIssue {issue_id} has no authored markdown — run the digest "
            f"pipeline to 'preview' before generating a video script."
        )

    articles = _split_articles(markdown)
    if not articles:
        raise RuntimeError(
            f"UpscIssue {issue_id}: could not find any '## N. Headline' "
            f"articles in the authored markdown."
        )

    sections: list[dict] = []

    intro = _intro_text(source, date_str, len(articles), lang)
    sections.append({
        "section_id": "intro",
        "label": "Intro",
        "text": intro,
        "est_seconds": est_seconds(intro),
    })

    # must-read + overview slides each get a short deterministic narration, kept
    # aligned with the branded-deck slide order (title, must-read, overview, …).
    if articles:
        if lang == "hi":
            mr_text = "सबसे पहले, आज की तीन सबसे ज़रूरी खबरें — इन्हें ज़रूर रिवाइज़ कर लीजिए।"
            ov_text = (f"आज हमने कुल {len(articles)} परीक्षा-केंद्रित खबरें कवर की हैं, "
                       "जो जनरल स्टडीज़ के अलग-अलग पेपर्स से जुड़ी हैं। चलिए एक-एक करके शुरू करते हैं।")
        else:
            mr_text = "First, the three must-read stories of the day — be sure to revise these."
            ov_text = (f"Today we cover {len(articles)} exam-relevant stories across the "
                       "General Studies papers. Let's go through them one by one.")
        sections.append({"section_id": "mustread", "label": "Must-read three",
                         "text": mr_text, "est_seconds": est_seconds(mr_text)})
        sections.append({"section_id": "overview", "label": "Overview",
                         "text": ov_text, "est_seconds": est_seconds(ov_text)})

    # Spoken-rewrite each article SEQUENTIALLY — exactly one Groq call at a time,
    # never concurrent. (Architect-locked: concurrency trips Groq's RPM; the async
    # worker, not parallelism, is what keeps this slow stage off the request path.)
    # The timestamp on each line lets the architect verify strict sequencing.
    for i, (headline, body_md) in enumerate(articles, start=1):
        print(f"  [{time.strftime('%H:%M:%S')}] spoken-rewrite {i}/{len(articles)}: "
              f"{headline[:60]!r}", flush=True)
        text = rewrite_article(headline, body_md, lang)
        sections.append({
            "section_id": f"art-{i:02d}",
            "label": f"{i}. {headline}"[:80],
            "text": text,
            "est_seconds": est_seconds(text),
        })

    outro = _outro_text(lang)
    sections.append({
        "section_id": "outro",
        "label": "Outro",
        "text": outro,
        "est_seconds": est_seconds(outro),
    })

    return sections


# =============================================================================
# CLI for manual testing
# =============================================================================

def _cli() -> None:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("issue_id", help="UpscIssue id (hex32) to build a script for.")
    ap.add_argument("--lang", default="hi", choices=["hi", "en"])
    args = ap.parse_args()
    sections = generate_script(args.issue_id, lang=args.lang)
    total = sum(s["est_seconds"] for s in sections)
    print(_json.dumps(sections, ensure_ascii=False, indent=2))
    print(f"\n{len(sections)} sections, ~{total:.0f}s (~{total/60:.1f} min)",
          file=sys.stderr)


if __name__ == "__main__":
    _cli()
