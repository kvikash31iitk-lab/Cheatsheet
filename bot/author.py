"""Author cheatsheet / book markdown from a transcript using Groq Llama.

Provider-agnostic: the active provider is set via env (AUTHORING_PROVIDER).
Today we ship the Groq path; OpenAI/Anthropic stubs are left for easy switch.

Map-reduce summarisation: Groq's free tier limits a single request to
~12K tokens, but real-world transcripts run 12-50K. So we split the
transcript on its existing ``## Chunk N`` markers, summarise each chunk
to a tight bullet list, then ask the model to author the final document
from the combined summaries.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional, Callable

from .config import (AUTHORING_MODEL, AUTHORING_PROVIDER, GROQ_API_KEY,
                     ANTHROPIC_API_KEY, OPENAI_API_KEY, CLAUDE_CODE_BIN)

ProgressFn = Optional[Callable[[str], None]]


# Token estimation — char-count heuristic, conservative for English+code.
def est_tokens(text: str) -> int:
    return max(1, len(text) // 3)  # 3 chars/token is a safe upper bound


# --- prompts ---------------------------------------------------------------

CHEATSHEET_SYSTEM = """You are a technical writer producing a compact 2-3 page cheatsheet from a video transcript.

OUTPUT FORMAT — must be valid markdown that follows this exact skeleton:

# <Concise topic title — no quotes, no parentheses with author name>

### <One-line context: e.g. "Cheat sheet - distilled from a NN-minute walkthrough">

## 1. <First main concept>

<paragraph or bullets distilling the concept>

| Heading | Heading |  ← tables welcome for comparisons
|---|---|
| ... | ... |

> [!def] <Short term>
> <Definition body>

## 2. <Next concept>
...

## N. Glossary
- **Term** - definition
- **Term** - definition

CALLOUT TYPES (use the exact bracket syntax shown):
- `> [!def]` — definitions
- `> [!example]` — concrete examples
- `> [!tip]` — pro tips
- `> [!warning]` — things to avoid
- `> [!revise]` — TL;DR / "mental shortcuts" — use ONCE near the end
- `> [!note]` — neutral notes

INLINE FORMATTING:
- **bold** for the 1-2 key terms per paragraph (renders highlighted)
- *italic* for emphasis
- `code` for filenames, commands, identifiers

RULES:
1. Aim for 6-8 numbered sections plus the Glossary. Each section short.
2. Length scales with content density: a 10-minute tutorial fits 2 pages, a 90-minute course may run 4-5. Don't pad; don't truncate. Cover what's actually taught.
3. The transcript is the source of truth. Do not invent facts.
4. Strip transcript filler ("uh", "you know", repeated phrases).
5. Do not refer to "the video", "the speaker", "the transcript". Write as if you are explaining the topic directly.
6. Output ONLY the markdown content. No preamble. No code-fence wrappers around the whole document.
7. Use `->` not `→` for arrows (the renderer is ASCII-friendly).
"""

BOOK_SYSTEM = """You are a technical writer producing a chapter-by-chapter illustrated book from a video transcript and a list of available image frames.

OUTPUT FORMAT — must be valid markdown that follows this exact skeleton:

# <Book title>

## Foreword

<2-3 short paragraphs setting up what this book covers and who it is for>

---

## Chapter 1 — <Chapter title>

### Why this chapter matters

<one short paragraph>

![<caption>](frames/<filename>.jpg)

### <Section heading>

<paragraphs / bullets / tables>

> [!def] <term>
> <definition>

> [!tip] <title>
> <pro tip body>

### <Another section>

...

> [!revise] Revise in 60 Seconds
> - <key point>
> - <key point>
> - <key point>

---

## Chapter 2 — <Chapter title>

(same structure)

...

## Glossary

> [!def] <Term>
> <definition>

CHAPTER STRUCTURE:
- Aim for 5-7 chapters depending on transcript length.
- Each chapter: "Why this chapter matters" → 2-4 sub-sections → "Revise in 60 Seconds" callout.
- Include 2-4 image references per chapter at moments where a frame matches the topic. Use the EXACT filename from the frames index provided.
- Use `> [!def]`, `> [!tip]`, `> [!warning]`, `> [!example]`, `> [!revise]`, `> [!note]` callouts liberally.
- End with a Glossary section of definition callouts.

CALLOUT BRACKET SYNTAX (exact):
> [!def] Term
> body line
> body line

INLINE:
- **bold** for the 1-2 key terms per paragraph
- *italic* for emphasis
- `code` for filenames, commands

RULES:
1. Image references MUST use only filenames from the FRAMES INDEX section of the user message. Do not invent paths.
2. The transcript is the source of truth. Do not invent facts.
3. Do not refer to "the video", "YouTube", "the speaker", "the transcript". Write as a textbook author.
4. Output ONLY the markdown. No preamble, no code-fence wrappers around the document.
5. Use `->` not `→` for arrows.
"""

SUMMARISE_SYSTEM = """You are condensing one section of a longer video transcript into a tight bullet list of facts and concepts that downstream document authors can use.

OUTPUT:
- 8-15 bullet points, one fact each.
- Each bullet starts with `- `.
- Preserve specific numbers, names, terms, file/command identifiers, examples.
- Drop filler ("uh", "you know", repeated phrases).
- Do NOT write paragraphs. No preamble. No headings. Bullets only.
- Use `->` not `→` for arrows.

The transcript chunk follows. Output bullets only.
"""


CHUNK_RE = re.compile(r"^##\s+Chunk\s+\d+", re.MULTILINE)
TPM_LIMIT_TOKENS = 10000   # safe budget per request on Groq free tier
INTER_CALL_DELAY_S = 8     # space requests so we stay under TPM windows


# --- post-processing ---------------------------------------------------------

def strip_wrappers(md: str) -> str:
    """Remove preamble lines and outer code fences the model sometimes adds."""
    md = md.strip()
    # Strip outer ```markdown ... ``` fence
    if md.startswith("```"):
        first_nl = md.find("\n")
        if first_nl != -1:
            md = md[first_nl + 1:]
        if md.endswith("```"):
            md = md[:-3]
        md = md.strip()
    # Strip "Here is the..." preamble before the first heading
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#"):
            md = "\n".join(lines[i:])
            break
    return md.replace("→", "->").strip() + "\n"


# --- providers ---------------------------------------------------------------

def _author_groq(system: str, user: str, *, max_tokens: int = 8000) -> str:
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    last_err = None
    for attempt in range(1, 4):
        try:
            resp = client.chat.completions.create(
                model=AUTHORING_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            last_err = exc
            wait = 10 * attempt
            print(f"[author] groq attempt {attempt}/3 failed: {exc}; waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Groq authoring failed after 3 attempts: {last_err}")


def _author_claude_code(system: str, user: str, *, max_tokens: int = 8000) -> str:
    """Invoke the Claude Code CLI in headless print mode.

    Bills against the user's Max subscription, not the API. The CLI must be
    logged in on the host (run `claude` interactively once to set up auth).
    The full prompt is piped via stdin to avoid command-line length limits.

    Retries: 3 attempts. The first retry waits 60s (transient blip); the
    second waits 600s (10 min) — long enough to clear most Max-plan rate
    windows. Each attempt captures BOTH stdout and stderr so the surfaced
    error reveals whether it was a rate limit, auth issue, etc.
    """
    import subprocess
    full_prompt = f"{system}\n\n---\n\n{user}"
    cmd = [CLAUDE_CODE_BIN, "-p"]
    backoffs = [60, 600]  # waits before retry 2 and retry 3
    last_msg = ""
    for attempt in range(1, 4):
        try:
            res = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
            if res.returncode == 0 and (res.stdout or "").strip():
                return res.stdout
            # Failure path — gather everything we have to surface upstream.
            stdout = (res.stdout or "").strip()
            stderr = (res.stderr or "").strip()
            last_msg = (f"exit={res.returncode} "
                        f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}")
        except subprocess.TimeoutExpired:
            last_msg = "timed out after 900s"
        except Exception as exc:
            last_msg = f"{type(exc).__name__}: {exc}"
        print(f"[author] claude CLI attempt {attempt}/3 failed: {last_msg}",
              flush=True)
        if attempt < 3:
            wait = backoffs[attempt - 1]
            print(f"[author] sleeping {wait}s before retry "
                  "(rate-limit recovery)...", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Claude Code authoring failed after 3 attempts. "
                       f"Last error: {last_msg}")


def _author(system: str, user: str, *, max_tokens: int = 8000) -> str:
    if AUTHORING_PROVIDER == "groq":
        return _author_groq(system, user, max_tokens=max_tokens)
    if AUTHORING_PROVIDER == "claude_code":
        return _author_claude_code(system, user, max_tokens=max_tokens)
    raise NotImplementedError(
        f"AUTHORING_PROVIDER={AUTHORING_PROVIDER!r} not wired yet — switch to "
        "'groq' / 'claude_code' or extend bot/author.py"
    )


def _needs_condensation() -> bool:
    """Return True if the active provider has tight TPM limits (forcing map-reduce)."""
    return AUTHORING_PROVIDER == "groq"


# --- map-reduce condensation ------------------------------------------------

def split_transcript(transcript: str, max_chunk_tokens: int) -> list[str]:
    """Split on ``## Chunk N`` markers; further bisect any oversized chunk."""
    parts = CHUNK_RE.split(transcript)
    headers = CHUNK_RE.findall(transcript)
    # Re-attach headers so the model sees timestamps.
    chunks: list[str] = []
    if parts and parts[0].strip():
        chunks.append(parts[0].strip())
    for hdr, body in zip(headers, parts[1:]):
        chunks.append(f"{hdr}{body}".strip())
    if not chunks:
        chunks = [transcript]
    # Bisect any chunk that exceeds the budget.
    out: list[str] = []
    for c in chunks:
        if est_tokens(c) <= max_chunk_tokens:
            out.append(c); continue
        # Split by lines into halves recursively.
        lines = c.splitlines()
        mid = len(lines) // 2
        out.extend(split_transcript("\n".join(lines[:mid]), max_chunk_tokens))
        out.extend(split_transcript("\n".join(lines[mid:]), max_chunk_tokens))
    return [c for c in out if c.strip()]


def condense(transcript: str, on_progress: ProgressFn = None) -> str:
    """Map-reduce: summarise each chunk to bullets, then return concatenation."""
    # Reserve room for the system prompt (~1.2K tokens) and output (~600).
    chunk_budget = TPM_LIMIT_TOKENS - 1800
    chunks = split_transcript(transcript, chunk_budget)
    if len(chunks) == 1 and est_tokens(chunks[0]) < chunk_budget - 1500:
        # Already small enough — no condensation needed.
        return chunks[0]

    summaries: list[str] = []
    for i, c in enumerate(chunks, 1):
        if on_progress:
            on_progress(f"Summarising chunk {i}/{len(chunks)}...")
        s = _author(SUMMARISE_SYSTEM, c, max_tokens=600)
        summaries.append(f"### Section {i}\n{s.strip()}")
        if i < len(chunks):
            time.sleep(INTER_CALL_DELAY_S)
    return "\n\n".join(summaries)


# --- public API --------------------------------------------------------------

def author_cheatsheet(transcript_path: Path, *, title_hint: Optional[str] = None,
                      duration_seconds: Optional[float] = None,
                      on_progress: ProgressFn = None) -> str:
    """Return cheatsheet markdown text. Caller writes it to disk."""
    transcript = Path(transcript_path).read_text(encoding="utf-8")
    if _needs_condensation():
        body = condense(transcript, on_progress=on_progress)
        body_label = ("CONDENSED TRANSCRIPT "
                      "(already factually trimmed bullet summaries by section):")
    else:
        body = transcript
        body_label = "TRANSCRIPT (raw with timestamps):"
    user_msg = "\n".join(p for p in [
        f"TITLE HINT: {title_hint}" if title_hint else "",
        (f"SOURCE LENGTH: {duration_seconds/60:.0f} minutes"
         if duration_seconds else ""),
        "",
        body_label,
        body,
    ] if p is not None)
    if on_progress:
        on_progress("Writing cheatsheet...")
    raw = _author(CHEATSHEET_SYSTEM, user_msg, max_tokens=3500)
    return strip_wrappers(raw)


def author_book(transcript_path: Path, frames_index_path: Path, *,
                title_hint: Optional[str] = None,
                duration_seconds: Optional[float] = None,
                on_progress: ProgressFn = None) -> str:
    """Return illustrated-book markdown. Caller writes it and renders the PDF."""
    transcript = Path(transcript_path).read_text(encoding="utf-8")
    if _needs_condensation():
        body = condense(transcript, on_progress=on_progress)
        body_label = "CONDENSED TRANSCRIPT (bullet summaries by section):"
    else:
        body = transcript
        body_label = "TRANSCRIPT (raw with timestamps):"
    frames = json.loads(Path(frames_index_path).read_text(encoding="utf-8"))
    frames_lines = "\n".join(
        f"  - t={f['timestamp']:>7.1f}s  {f['file']}" for f in frames
    )
    user_msg = (
        (f"TITLE HINT: {title_hint}\n" if title_hint else "")
        + (f"SOURCE LENGTH: {duration_seconds/60:.0f} minutes\n"
           if duration_seconds else "")
        + "\nFRAMES INDEX (you may reference any of these by filename):\n"
        + frames_lines
        + f"\n\n{body_label}\n"
        + body
    )
    if on_progress:
        on_progress("Writing illustrated book...")
    raw = _author(BOOK_SYSTEM, user_msg, max_tokens=8000)
    return strip_wrappers(raw)
