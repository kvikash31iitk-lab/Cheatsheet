# Cheatsheet AI - Engineering Rules & Architectural Invariants

This document serves as the permanent reference and checklist for all agents and developers modifying the Cheatsheet codebase. **Every change must adhere to these invariants to prevent breaking existing functionality.**

---

## 1. Directory & Environment Invariants

1. **Active Primary Workspace:**
   * Primary root is `C:\Users\HP\VIkash\Cheetsheet`.
   * All commands, backend routes, frontend components, and tests must execute directly against this workspace.
   * Do not copy intermediate files to arbitrary directories (e.g. `Downloads`) unless explicitly initiated by the user.

2. **Saved Files & ZIP Naming Invariant:**
   * **NEVER** save files or zip contents named after raw YouTube video IDs (e.g. `002_03FeQRI7KjI.pdf`, `ZTWSHhg2-Mk.pdf`).
   * Every single PDF, Markdown note, and ZIP entry must have its clean, human-readable video title extracted from `source.json` / `meta.json` or Markdown `# Title`.
   * Strip repetitive channel boilerplate and instructor tags (`| By Anurag Sir`, `UPSC EPFO AO/EO & APFC |`).
   * Inside Playlist ZIPs, modules must be numbered sequentially: `01. <Clean Title> - <Kind>.pdf`.
   * All outputs are automatically synced to `C:\Users\HP\VIkash\Cheetsheet\saved files/` via `bot.file_saver.save_generated_artifacts`.

---

## 2. ReportLab & XML Paraparser Safety Rules

1. **Tag & Attribute Protection in Math / Subscript Cleaners:**
   * LaTeX subscript converters (e.g. `_ELpb28k` -> `<sub>ELpb28k</sub>`) must **NEVER** run inside existing HTML tags or attribute values (`<a name="...">`, `<font color="...">`, `<img>`).
   * Only match single-symbol math subscripts (e.g., `x_1`, `H_2O`, `a_0`) using `re.sub(r'(?<=[a-zA-Z])_([0-9]{1,2}|[ijkmnpt])(?![a-zA-Z0-9_-])', r'<sub>\1</sub>', text)`.
   * Anchor IDs must always be sanitized: `anchor = re.sub(r'[^a-zA-Z0-9-]', '-', raw_anchor).strip('-')`.

2. **Self-Healing Flowable Fallback (`make_para`):**
   * All ReportLab `Paragraph` constructions across `build_cheatsheet.py`, `build_mcq_handbook.py`, and `build_illustrated_book.py` must use `make_para(text, style)`.
   * If ReportLab's `paraparser` raises an XML syntax error on any malformed token, `make_para` automatically catches the error, strips raw tags (`re.sub(r'<[^>]*>', '', text)`), escapes basic XML entities, and renders clean plain text so the document **never crashes**.

3. **Table & KeepTogether Height Constraint:**
   * In ReportLab Platypus, never nest a multi-row table inside a `KeepTogether` block if the total height can exceed `763pt` (the printable page frame height).
   * Headers and options use `keepWithNext=True` or compact `KeepTogether(120pt)` wrappers, while explanation bodies and tables flow naturally across pages (`splitByRow=1`).

---

## 3. Typography & Styling Invariants

1. **Mathematical Fraction Formatting:**
   * Never render raw LaTeX text like `\frac{A}{B}` or `frac{A}{B}`.
   * `_clean_latex_math()` uses balanced-brace extraction to un-nest `\frac{A}{B}` into arithmetic notation `(A) / (B)` with proper sub/superscripts.
   * Greek symbols ($\alpha, \beta, \Delta, \sigma$), roots ($\sqrt{x} \to \sqrt{(x)}$), and operators ($\approx, \pm, \le, \ge$) are cleanly mapped to Helvetica-safe ReportLab typography.

2. **Zero Ink-Waste & High-Contrast Callouts:**
   * Callout box bodies must have a pure white background (`spec["tint"] = colors.HexColor("#FFFFFF")`) with a `0.5pt` subtle outer outline (`#E2E8F0`).
   * Retain a solid `3.5pt` left accent border and colored top title pill (`spec["bar"]`).
   * This guarantees that keyword highlights (`[red]`, `[blue]`, `[green]`, bold text) pop with 100% contrast while saving printer toner.

3. **MCQ Continuous Flow Layout:**
   * Never wrap an entire question + all explanation callouts in a monolithic `KeepTogether`.
   * Only wrap `Question Statement + 4 Options` in `KeepTogether` (~100–120pt max height).
   * Explanations and tip boxes flow immediately below or break cleanly across page boundaries, eliminating artificial 40% blank gaps at the bottom of pages.

---

## 4. LLM Authoring & Token Budget Invariants

1. **Multilingual BPE Token Estimation:**
   * In `bot/author.py`, `est_tokens()` must use UTF-8 byte density: `max(1, int(utf8_bytes / 2.5), char_len // 3)`.
   * Hindi/Devanagari text consumes ~2.5 bytes per token. Pure character length undercounts Hindi tokens by ~300% and triggers Groq 413 limit errors.

2. **Groq Model Rotation:**
   * Maintain the resilient 6-model fallback rotation in `bot/author.py` (`llama-3.3-70b-versatile` -> `qwen-2.5-32b` -> `llama-3.1-8b-instant` -> `gemma2-9b-it`).

---

## 5. Verification Checklist Before Any Commit

Before completing any task or pushing changes:
1. Run the regression test suite:
   ```bash
   python -X utf8 -m unittest tests.test_author_limits tests.test_author_quality tests.test_pdf_robustness
   ```
2. Verify all 3 builders (`build_cheatsheet.py`, `build_mcq_handbook.py`, `build_illustrated_book.py`) compile sample documents without ReportLab errors.
3. Test that `START_CHEATSHEET.bat` and `UPDATE_CHEATSHEET.bat` execute cleanly without hangs.
