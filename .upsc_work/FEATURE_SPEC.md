# UPSC Daily Digest — feature spec

A new product line on Cheetsheet that turns a daily newspaper PDF into an exam-targeted digest for UPSC Civil Services aspirants.

## Why this is a *new kind*, not a feature flag

| Dimension | YouTube cheatsheet/book | UPSC digest |
|---|---|---|
| Input | YouTube URL | Newspaper PDF (e-paper) |
| Pipeline | yt-dlp → ffmpeg → Whisper → LLM → PDF | PDF text + OCR fallback → article segmentation → per-article LLM → PDF |
| Output schema | One subject, ~6-8 sections | 6-12 articles, each with the same internal structure |
| Cache key | video_id + features | newspaper_name + date + features |
| User cadence | Ad-hoc per video | Daily, scheduled (~7:30 AM IST) |
| Pricing | ₹1 / 30-min slab | Suggested: ₹2 per issue OR ₹150/month sub |

Recommendation: add `kind = "upsc_digest"` to the existing `Generation` schema (already has `kind` column — books and cheatsheets coexist there).

## Input pipeline

1. **PDF upload** via web form (or admin-fetch via Indian Express e-paper subscription scraper).
2. **Text extraction** — first try PyMuPDF; if fonts are subset (like the IE HD PDF, see Story 6 of the sample), fall back to render-each-page-to-PNG + Tesseract OCR.
3. **Article segmentation** — heuristic: find headline-styled spans (font size ≥ body × 1.4, bold, top-of-column), each headline starts a new article. Drop ads (high colour density, no headlines, page > 60% covered with image).
4. **UPSC classification** — pass each article (headline + first 200 words) to a cheap LLM with a "classify into GS1/2/3/4/None" prompt. Drop None.
5. **Per-article authoring** — for the top N (8-12) survivors, run a richer LLM prompt that produces the schema below.
6. **PDF render** — reuse `build_illustrated_book.py` with feature flags `tldr`, `qna`, `chapters`, plus a new `prelims_mains` flag that wraps Q&A in coloured callouts.

## Per-article output schema

```
## {N}. {Headline}

> [!tldr] Why in news
> {1-3 lines on the trigger event}

**Paper / GS:** GS-{N} (...) · **Optional:** {if applicable} · **Static link:** {comma-list of static topics}

### Background — what is being proposed / what happened

### Key facts a UPSC answer must carry
| Item | Value / Detail |
|---|---|
...

### {Critical analysis section — pros / cons / way forward}

> [!warning] Watch the trap   ← optional, for common confusions
> ...

> [!q] Prelims practice
> 1. MCQ with 4 options, correct answer bolded
> 2. MCQ

> [!q] Mains practice ({mark count} marks)
> "{Question}"
```

Plus standard annexures:
- Personalities in news
- Places in news
- Schemes / Acts / Reports mentioned
- 10-question Prelims quickfire
- Static + current linkage table
- Glossary

## New feature flags this product unlocks

| Flag | Effect |
|---|---|
| `prelims_only` | Strip Mains questions, keep MCQs. ~30% shorter PDF. |
| `mains_only` | Strip MCQs, expand critical-analysis sections. For Mains-stage students. |
| `mindmap` | Auto-generate a `mermaid` mindmap per article (Static topic at centre, current news as branches). Reuses existing `mermaid` flag plumbing. |
| `optional_{subject}` | Append optional-paper relevance for PSIR / Public Admin / Geography / Sociology / Anthropology aspirants. |
| `audio_briefing` | TTS the executive summary into a 5-min MP3 (commute companion). |

## Pricing notes

Per-issue cost on current stack (with Max 5x sub + Groq Whisper free): **near-zero marginal**. Recommended end-user pricing:

| Plan | Price | What it includes |
|---|---|---|
| Free | ₹0 | 3 issues / week, no annexures |
| Plus | ₹99 / month | Daily issue, all annexures, Telegram delivery |
| Pro | ₹199 / month | Daily issue + weekly compilation + monthly themed PDFs (Yojana-style) |

## Why this is a strong wedge

1. UPSC aspirants spend 60-90 min/day reading newspapers and another 30 min making notes. A 15-page PDF in their inbox at 7:30 AM saves 90 min/day.
2. Existing competitors (Drishti, Vision IAS, ForumIAS) sell hand-curated daily digests at ₹150-300/month with a 1-3 day lag and patchy quality control. An LLM pipeline with proper UPSC-tuned prompts can match coverage with 0-day lag at ₹99.
3. The audience is concentrated (10 lakh+ active aspirants), high-intent (paying for coaching at ₹50k-1L per year), and trains itself to read every day → built-in retention.
4. Same pipeline extends naturally to State PSCs, Bank PO, CAT, MBA case-prep — each is a 1-day prompt-tuning sprint.

## Implementation plan (~3 days of work)

| Day | Tasks |
|---|---|
| 1 | PDF upload + text extraction + OCR fallback. Article segmentation heuristic. Admin endpoint to dry-run on uploaded PDFs. |
| 2 | Classification prompt + per-article authoring prompt. Wire to existing `build_illustrated_book.py` with the schema above. |
| 3 | Web `/upsc` page (upload + scheduled delivery toggle), Telegram delivery, pricing/wallet integration, scheduling cron. |

Suggested order of build:
1. Get the LLM authoring pipeline rock-solid on a hand-curated newspaper text dump (no extraction logic yet).
2. Add the text-extraction + OCR-fallback step.
3. Add the daily-scheduled e-paper fetch (toughest part — Indian Express e-paper requires subscription cookies).
4. Ship to a closed beta of 50 UPSC aspirants for 2 weeks before public launch.

## Open product questions

- **E-paper access**: Indian Express e-paper PDF requires a paid subscription. Cleanest legal path is to (a) require the user to upload the PDF themselves, or (b) negotiate B2B access with IE for a syndication fee. Option (a) is the cheap MVP.
- **Multi-paper support**: aspirants typically read 1-2 papers (IE + The Hindu most common). Day-1 should support IE + Hindu; rest later.
- **Hindi / Vernacular**: 40% of UPSC aspirants prep in Hindi. Day-1 English, Hindi version a week later via a single prompt-translate step.
