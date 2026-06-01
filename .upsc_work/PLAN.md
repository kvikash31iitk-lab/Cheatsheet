# UPSC Cheetsheet — Implementation Plan

**Status:** planning complete, ready to implement
**Style:** locked to `dense_tight` (rendered by `.upsc_work/render_dense_tight.py`)
**Approved sample:** `.upsc_work/sample_digest_dense_tight.pdf` (36 pages, 84 KB)

---

## Resume prompt (paste this at home or office PC)

```
Continue the UPSC Cheetsheet feature. Read .upsc_work/PLAN.md first, then start
at step 1 (data model in api/models.py). The PDF style is locked — sample at
.upsc_work/sample_digest_dense_tight.pdf, rendered by
.upsc_work/render_dense_tight.py. Hand-curated v2 markdown at
.upsc_work/sample_digest_v2.md is the schema target for the LLM authoring
prompt. Don't change the style without asking.
```

---

## Decisions locked

| Question | Decision |
|---|---|
| Public URL | `cheetsheet.tech/upsc/<YYYY-MM-DD>` (path, not subdomain) |
| Running header | `UPSC CHEETSHEET` |
| First issue | Old issues backfilled by admin (not day-1-fresh) |
| Cover QR | Points to per-issue URL (`cheetsheet.tech/upsc/<date>`) |
| `[!tldr]` callout label | Rename to **"Why in news"** |
| Body alignment | Justify body + callout paragraphs (bullets/tables stay left) |
| Admin flow | Preview-before-publish (manual click) |
| Style picker in admin | Yes — 4 options, `dense_tight` default |
| Source | Free-form text (Indian Express, The Hindu, etc.) |
| Hard cap | 12 articles per issue (admin slider 8-15) |
| Re-author button | Yes — admin can re-trigger the LLM authoring step |
| Telegram auto-post | Deferred |
| Pricing | Deferred |

---

## 1. Data model — `api/models.py`

**Two new tables**: `UpscIssue` (one row per uploaded newspaper) and `Pyq` (the verified Previous-Year-Question corpus — see §3.5 for full schema).

```python
class UpscIssue(Base):
    __tablename__ = "upsc_issues"
    id                : PK
    issue_date        : Date, unique, indexed
    source            : str (free-form, e.g. "Indian Express")
    title             : str (default "UPSC Cheetsheet · {date}")
    style             : str (default "dense_tight"; one of 5)
    status            : str  uploaded → extracting → authoring → rendering
                              → preview → published | error
    input_pdf_path    : str
    output_pdf_path   : str (nullable)
    markdown          : text (nullable; admin-editable)
    summary           : text (2-line for landing page)
    cover_thumb_path  : str (page-1 PNG for OG image + listing thumbnail)
    article_count     : int (default 0)
    error             : text (nullable)
    llm_tokens_in / out / cost_paise : int (defaults 0)
    created_at, published_at
```

Both tables auto-create on FastAPI startup via existing `Base.metadata.create_all`.

---

## 2. Backend routes — `api/main.py`

**Admin** (gated by existing `require_admin` dependency):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/admin/upsc/upload` | multipart: pdf + date + source + optional title. Inserts row, kicks `process_upsc_issue()` via `BackgroundTasks`. |
| GET | `/api/admin/upsc/issues` | List paged, with thumbnails. |
| GET | `/api/admin/upsc/issues/{id}` | Single issue + preview PDF URL. |
| PATCH | `/api/admin/upsc/issues/{id}` | Edit markdown/style/title → triggers re-render. |
| POST | `/api/admin/upsc/issues/{id}/publish` | Publish. |
| POST | `/api/admin/upsc/issues/{id}/unpublish` | Reverse publish. |
| POST | `/api/admin/upsc/issues/{id}/reauthor` | Re-trigger LLM authoring (preserves edits unless overridden). |
| DELETE | `/api/admin/upsc/issues/{id}` | Hard delete (testing). |

**Public** (unauthenticated; existing middleware leaves these alone):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/public/upsc/issues` | List of published, newest first, paged. |
| GET | `/api/public/upsc/issues/{date}` | Single issue metadata. |
| GET | `/api/public/upsc/pdf/{date}` | `FileResponse`, `Cache-Control: public, max-age=86400`. |
| GET | `/api/public/upsc/thumb/{date}` | Cover PNG. |

---

## 3. Processing pipeline — new `scripts/upsc_pipeline.py`

Four async stages, DB `status` field updated after each:

| # | Stage | Tool | Notes |
|---|---|---|---|
| 1 | extract | PyMuPDF → OCR fallback (Tesseract or render-as-PNG + vision) | IE HD uses subset `GraphikComp` fonts with broken glyph→Unicode; OCR is mandatory for those files |
| 2 | classify | Sonnet (cheap) | Drop ads + non-UPSC stories. Output: 12-15 candidates with paper-tag. |
| 3 | author | Sonnet for stories, Opus for editorial | One prompt per article filling the v2 schema. Hard cap 12. **PYQ citations must come from `pyq` table via `find_pyqs(static_topics)` — never LLM-generated.** |
| 4 | render | `build_illustrated_book.build()` + style applier | `dense_tight` default; can be overridden by admin |

**New prompt files:**
- `bot/prompts/upsc_classify.md`
- `bot/prompts/upsc_author.md`

**Refactor:** move the style appliers (`apply_dense_tight`, `style_academic`, etc.) from `.upsc_work/render_*.py` into a new `scripts/digest_styles.py` so they're importable from the pipeline.

**Cover overrides per issue:** `RUNNING_HEADER = "UPSC CHEETSHEET"`, QR `source_url = f"https://cheetsheet.tech/upsc/{issue_date}"`.

---

## 3.5. PYQ corpus — new `scripts/seed_pyq_corpus.py` + `pyq` table

**Why:** without a real corpus, the authoring step will fabricate PYQ years and marks. One fake citation = lost trust. This is a hard prerequisite for the public launch, not optional polish.

**Data model — new table in `api/models.py`:**

```python
class Pyq(Base):
    __tablename__ = "pyq"
    id              : PK
    year            : int, indexed              # 2013-2025
    exam_stage      : str  "prelims" | "mains"
    paper           : str  "GS-1" | "GS-2" | "GS-3" | "GS-4" | "essay" | "CSAT" | "optional-<subject>"
    section         : str  nullable             # "A" / "B" for Mains GS papers, "Section A" / "Section B" for essay
    question_num    : int  nullable
    question_text   : text
    marks           : int  nullable             # 10 / 12.5 / 15 / 20 / 25 / 250 (essay)
    static_topics   : JSON text                 # list of syllabus tags, derived once on seed
    source_url      : str  nullable             # link to UPSC PDF
    created_at      : datetime
```

Compound index on `(year, paper)` for browse; a separate full-text index on `question_text` for fuzzy match.

**Source data:** [upsc.gov.in](https://upsc.gov.in) publishes all Prelims + Mains papers as PDFs in `Previous Question Papers` section, organised by year. Coverage target: **2013-2025, all GS papers + Essay + CSAT** (~3,500-4,000 questions). Optional papers later.

**Seed pipeline:**
1. Scrape the UPSC archive index page for PDF links by year.
2. Download each PDF (cache locally so we don't re-hit UPSC).
3. Parse text with PyMuPDF; if a paper is image-only (rare for UPSC papers), OCR fallback.
4. Question segmentation: heuristic on numbered list patterns (`1. ...`, `(a) ...`) + marks-in-brackets (`(10)`, `(15)`).
5. Pass each parsed question to a cheap LLM (Sonnet) to:
   - Confirm it's actually a question (drop instructions / preambles).
   - Tag with 1-3 syllabus topics from the syllabus tree (see Step 3.6 if we build that too).
6. Insert into `pyq` table.

**Effort:** 1-2 days end-to-end. Probably 4-6 hours of LLM time for tagging (~$5-10 on Sonnet, or free on Anthropic Max sub).

**Pipeline integration** (modifies Step 3 of `upsc_pipeline.py`):
- After classification, for each surviving article, derive `static_topics` from headline + body.
- Call `find_pyqs(static_topics, limit=3)` → returns up to 3 closest matches by tag overlap (fall back to BM25 on `question_text` if no tag hits).
- Pass those 3 PYQs to the authoring prompt as part of its context.
- Authoring prompt instruction: *"You may only cite PYQs from the supplied list. If none of them is a close enough match, write 'No close PYQ in archive — broader topic last asked in {year}.' Never invent a year, marks, or question text."*

**Post-render validator** (cheap safety net): grep the rendered markdown for `Mains|Prelims \w*-?\d* \d{4}` patterns. If any cited (year, paper, marks) tuple doesn't exist in the `pyq` table, mark issue status as `error: unverified_pyq_citation` and surface to admin before publish. Catches LLM ignoring the instruction.

**Admin endpoint** (one-time): `POST /api/admin/pyq/reseed` — re-run the seed pipeline (idempotent on `(year, paper, question_num)`). For when UPSC adds the next year's papers.

---

## 4. Frontend pages — Next.js App Router

**Admin** (under existing `/admin/*` protection in `web/middleware.ts`):

| File | Purpose |
|---|---|
| `web/app/admin/upsc/page.tsx` | List of all issues + status badges + upload form (modal or inline). |
| `web/app/admin/upsc/[id]/page.tsx` | Embedded PDF preview · markdown editor · style picker · Publish / Re-render / Re-author / Unpublish buttons. |

**Public** (unauthenticated; middleware leaves `/upsc/*` alone):

| File | Purpose |
|---|---|
| `web/app/upsc/page.tsx` | Hero card for latest issue + grid of recent issues. |
| `web/app/upsc/[date]/page.tsx` | Cover image · summary · embedded PDF · Download button · OG meta tags for shareable WhatsApp/Twitter previews. |

---

## 5. One-off PDF style tweaks (affect all kinds, not just UPSC)

In `scripts/build_illustrated_book.py`:

- `CALLOUTS["tldr"]["label"]` → `"Why in news"` (replace the existing "TL;DR"-style default).
- `CO_BODY` `ParagraphStyle` → `alignment = TA_JUSTIFY` (currently `TA_LEFT`).

Body is already justified. Bullet list items and table cells stay left-aligned.

---

## 6. Build order

| # | Step | Effort |
|---|---|---|
| 1 | Data model (`UpscIssue` + `Pyq` tables) + auto-create | 30 min |
| 2 | **PYQ corpus seed** — `scripts/seed_pyq_corpus.py`, scrape UPSC archive 2013-2025, populate `pyq` table. Hard prerequisite for step 3. | 1-2 d |
| 3 | `scripts/upsc_pipeline.py` end-to-end against the June-1 IE PDF, local run. Includes `find_pyqs()` lookup + post-render validator. | 3-4 h |
| 4 | Eight backend routes (seven from §2 + `POST /api/admin/pyq/reseed`) | 1 h |
| 5 | Admin UI (`/admin/upsc/*`) | 1.5 h |
| 6 | Public UI (`/upsc/*`) | 2 h |
| 7 | PDF style tweaks (label + justify) | 15 min |
| 8 | Deploy + smoke test on `cheetsheet.tech` | 30 min |

**Total: ~2-3 days end-to-end** (was 8-10 h before the PYQ corpus was added; the seed is the biggest single chunk). Suggested branch: `feat/upsc-digest`, 5-6 commits along the step boundaries.

---

## 7. Files in `.upsc_work/` (planning artifacts, not shipped to prod)

- `PLAN.md` — this file
- `FEATURE_SPEC.md` — original product spec (kept for context)
- `render_dense_tight.py` — final renderer (logic moves to `scripts/digest_styles.py` during impl)
- `render_styles.py` — 4-style variant generator (reference for the admin style picker)
- `sample_digest_v2.md` — hand-curated 15-article markdown (use as fixture for LLM authoring prompt + as the schema reference)
- `sample_digest_dense_tight.pdf` — **locked-in style sample** (do not change look without re-asking)
- `sample_digest_{academic,dense,coaching,magazine}.pdf` — the 4 style variants shown to the user before lock-in

---

## 8. Deferred (not this round)

- Telegram auto-post on publish
- Weekly compilation cron (Mon-Sat → one Sunday PDF)
- Topic pages (`/upsc/topic/polity`, `/upsc/topic/economy`)
- Hindi version (URL slot reserved: `/upsc/<date>/hi`)
- Auto IE e-paper fetch (subscription / legal grey area)
- Pricing / wallet integration
- B2 backup mirror

All of these slot in without schema changes because the data model already carries `source` and the URL already has a `<date>` slot.
