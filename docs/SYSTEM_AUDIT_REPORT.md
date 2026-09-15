# Cheetsheet AI — Comprehensive System, Code & Infrastructure Audit Report

**Date:** September 14, 2026  
**Scope:** FastAPI Backend, ReportLab PDF Compilation Engines, Telegram Bot, Next.js Web Frontend, VPS Deployment, and Desktop Packaging Pipelines.

---

## Executive Summary

A comprehensive architectural and code audit was conducted across the Cheetsheet codebase. While core components (such as transcript ingestion, chunking, and the new refined ReportLab compilation engine) are robust, critical operational risks were identified in the host VPS configuration, desktop packaging distribution, and API routing.

---

## 1. Critical Operational & Stability Risks (Severity: 🔴 HIGH)

### 🔴 1.1 Telegram Bot Infinite Crash Loop on Hostinger VPS
- **Location:** VPS (`93.127.185.243`) $\to$ `/etc/systemd/system/video-notes-bot.service`
- **State:** The service is failing in a continuous restart loop (restart counter: >10,400 attempts), restarting and failing every 15 seconds.
- **Root Cause:**
  - `[config] FATAL: TELEGRAM_BOT_TOKEN missing in .env`
  - `[config] FATAL: WHITELISTED_GROUP_IDS is empty — bot would respond nowhere`
- **Impact:** Continuous CPU thrashing on the VPS and bloated systemd journal logs.
- **Remediation:** If the Telegram bot is unused, run `systemctl disable --now video-notes-bot.service`. If intended for production, set `TELEGRAM_BOT_TOKEN` and `WHITELISTED_GROUP_IDS` in `/opt/video-notes-bot/.env`.

### 🔴 1.2 Broken Desktop Package Distribution Pipeline
- **Location:** `scripts/package_desktop_release.py:24-28` and `START_CHEATSHEET.bat`
- **Root Cause:**
  - `package_desktop_release.py` explicitly excludes `.next` and `node_modules` from the release zip.
  - `START_CHEATSHEET.bat` does not run `npm install` or `npm run build`.
  - `scripts/launch_desktop_app.py` directly executes `npm start` (`next start -p 3000`).
- **Impact:** Any user downloading `Cheatsheet_Desktop_Latest.zip` on their home PC encounters an immediate, silent crash on launch because `next start` requires a pre-built `.next` production bundle.
- **Remediation:** In `START_CHEATSHEET.bat` (or a setup script), verify if `web/node_modules` and `web/.next` exist. If absent, prompt or run `npm --prefix web ci && npm --prefix web run build`.

### 🔴 1.3 Hardcoded Local Windows User Path in Public API Route
- **Location:** `api/playlist_routes.py:650`
- **Root Cause:**
  `docx_file = Path("C:/Users/Vikash PC/Downloads/Complete_Modern_Indian_History_13Hours_Master_Handbook_40Pages.docx")`
- **Impact:** Calling `@router.get("/download/history-handbook-docx")` on the Linux VPS or any other client machine raises a guaranteed HTTP 404 error.
- **Remediation:** Store static downloads relative to `PROJECT_ROOT / "data" / ...` with fallback resolution.

### 🔴 1.4 Production `/api/me` Overriding Quotas with Hardcoded 9999
- **Location:** `api/main.py:888-892`
- **Root Cause:**
  Hardcoded values:
  - `"free_cheatsheets_left": 9999`
  - `"free_books_left": 9999`
  - `"free_cheatsheets_per_day": 9999`
  - `"free_books_per_day": 9999`
  - `"wallet_balance_paise": 999900`
- **Impact:** Bypasses database quota counting (`_daily_used`), allowing unrestricted access and displaying dummy wallet balances on the web UI.
- **Remediation:** Hook the return dictionary back to computed `free_limits` and actual `user.wallet_balance_paise`.

---

## 2. Pipeline & Core Engine Inconsistencies (Severity: 🟡 MEDIUM)

### 🟡 2.1 `AUTHORING_PROVIDER` Stubs Throwing `NotImplementedError`
- **Location:** `bot/author.py:1260-1263`
- **Root Cause:** While `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are imported from configuration, selecting `AUTHORING_PROVIDER="openai"` or `"anthropic"` throws `NotImplementedError`.
- **Impact:** Admins configuring OpenAI or Anthropic directly via environment variables will see tasks fail immediately.
- **Remediation:** Either implement direct HTTP/SDK calls for OpenAI and Anthropic, or remove them from options if only Groq, Gemini, Ollama, and CLI sidecars are supported.

### 🟡 2.2 Hardcoded Cheatsheet Override on Playlist Retries
- **Location:** `api/playlist_routes.py:131-136`
- **Root Cause:** Retrying failed videos inside `retry_playlist` hardcodes `kind="cheatsheet"` and `concurrency=3`.
- **Impact:** If a playlist was originally generated as an Illustrated Book (`kind="book"`) or Structured Notes, triggering a retry on failed items forcibly changes those items to `"cheatsheet"`.
- **Remediation:** Read `kind=manifest_data.get("kind", "cheatsheet")` and `concurrency=manifest_data.get("concurrency", 3)`.

### 🟡 2.3 Relative Subprocess Path in `download_desktop`
- **Location:** `api/main.py:2399`
- **Root Cause:** `subprocess.run([sys.executable, "scripts/package_desktop_release.py"])` executes without passing `cwd=PROJECT_ROOT`.
- **Impact:** If uvicorn is started from `/opt` or `api/`, calling `/api/download-desktop` raises `FileNotFoundError`.
- **Remediation:** Pass `cwd=str(PROJECT_ROOT)`.

### 🟡 2.4 MCQ Option Regex Gaps & Frame Overflow Risk
- **Location:** `scripts/build_mcq_handbook.py:555, 575`
- **Root Cause:**
  1. Option matching regex tests uppercase `[A-D]` only (`\([A-D]\)`). Lowercase options like `(a)`, `(b)` or `A.` fall back to generic bullet points.
  2. The entire question, problem, options, and comprehensive explanation are wrapped in a single `KeepTogether(q_flowables)` block.
- **Impact:** If an in-depth UPSC explanation exceeds a single A4 page (~40 lines), ReportLab throws `LayoutError: Flowable is too large to fit in frame`.
- **Remediation:** Make the regex case-insensitive `[a-dA-D]`, and bundle only `[Question + Options + Correct Answer Callout]` in `KeepTogether`, letting the lengthy explanation flow across pages.

---

## 3. Web Frontend & UI Navigation (Severity: 🟢 LOW)

### 🟢 3.1 Orphaned 2,088-Line UPSC Video Generation Dashboard
- **Location:** `web/app/admin/upsc/youtube/page.tsx`
- **Root Cause:** A complete video rendering, TTS narration, and slide generation dashboard exists, but there is no link to it in `web/components/admin-shell.tsx` or in `web/app/admin/upsc/page.tsx`.
- **Impact:** Features are hidden and only accessible by manually typing the URL into the browser address bar.
- **Remediation:** Add `{ href: '/admin/upsc/youtube', label: 'YouTube Studio', icon: <Ic.play size={14} /> }` to `admin-shell.tsx`.

### 🟢 3.2 Aggressive Localhost Redirect in Middleware
- **Location:** `web/middleware.ts:21-28, 46-51`
- **Root Cause:** `isLocalDesktop` matches any `host.includes('localhost')`. When matching, it redirects `/` and `/login` to `/generate`.
- **Impact:** A developer running the website locally at `localhost:3000` cannot view or test the landing page (`/`).
- **Remediation:** Limit the auto-redirect strictly to `process.env.DESKTOP_MODE === '1'` rather than generic `localhost`.

### 🟢 3.3 Hardcoded Development Paths in Legacy Cheatsheet Builder
- **Location:** `scripts/build_cheatsheet.py:36-38`
- **Root Cause:** Hardcoded Windows paths `C:\Users\HP\Documents\Claude\Video notes\...` left over from initial development, plus non-ASCII encoding artifacts (`â€”`).
- **Impact:** Running `python scripts/build_cheatsheet.py` directly without arguments crashes with path errors.
- **Remediation:** Update the script entry point to accept standard CLI arguments (as implemented in `scripts/build_cheatsheet_refined.py`).

---

## 4. Completed & Verified Fixes

- **Mermaid Visual Diagrams in PDF Engine:** Seamlessly integrated into `scripts/build_cheatsheet_refined.py` with dual-engine fallback (Kroki API + native VPS headless Chrome) and proportional card containers.
- **Zero-Orphan Heading Guarantee:** Implemented atomic header-content bundling (`emit` with `pending_headings`), ensuring no section banners (`##`) or subsections (`###`) are stranded at the bottom of pages.
- **LaTeX Math Typography & Subscript Rendering:** Formulas (`50% x Monthly Wage x Relevant Factor`) and subscripts (`C₈₇`, `C₉₈`) now render cleanly with zero black boxes or unescaped backslashes.
