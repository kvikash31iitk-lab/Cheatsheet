"""Author cheatsheet / book markdown from a transcript using Groq Llama.

Provider-agnostic: the active provider is set via env (AUTHORING_PROVIDER).
Today we ship the Groq path; OpenAI/Anthropic stubs are left for easy switch.

Map-reduce summarisation: Groq's free tier limits a single request to
8K tokens for the current Qwen authoring model, but real-world transcripts
run 12-50K. So we split the
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
                     GROQ_FALLBACK_MODELS,
                     ANTHROPIC_API_KEY, OPENAI_API_KEY, CLAUDE_CODE_BIN,
                     CODEX_CLI_BIN, OLLAMA_BASE_URL)

ProgressFn = Optional[Callable[[str], None]]


# Token estimation — char-count heuristic, conservative for English+code.
def est_tokens(text: str) -> int:
    return max(1, len(text) // 3)  # 3 chars/token is a safe upper bound


# --- prompts ---------------------------------------------------------------

CHEATSHEET_SYSTEM = """You are an expert technical author creating an authoritative, high-yield study cheatsheet from a video transcript.

TARGET DENSITY & PAGE BUDGET:
- For short tutorials (under 30 mins): Produce a compact 2-4 page cheatsheet (800 - 1,400 words) across 5-7 focused sections.
- For medium/long lectures (30 mins to 2+ hours): Produce a comprehensive 5-10 page deep-dive (2,000 - 4,500 words) across 8-15 detailed sections.
- Never truncate important concepts; scale the section count and depth directly with what is taught.

OUTPUT FORMAT — must be valid markdown that follows this exact skeleton:

# <Concise topic title — no quotes, no parentheses with author name>

### <One-line context: e.g. "Cheat sheet - distilled from a NN-minute walkthrough">

## 1. <First main concept>

<paragraph or bullets distilling the concept with exact logic and formulas>

| Heading | Heading |  ← tables welcome for comparisons and decision rules
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
- `> [!example]` — concrete examples & solved problems
- `> [!tip]` — pro tips & mental shortcuts
- `> [!warning]` — common exam pitfalls & traps to avoid
- `> [!revise]` — TL;DR / "Revise in 60 Seconds" recap
- `> [!note]` — neutral notes

INLINE FORMATTING:
- **bold** for key terms and rules
- *italic* for emphasis
- `code` for filenames, syntax formulas, identifiers

RULES:
1. Scale sections with duration: 5-7 sections for short videos, 8-15 sections for deep lectures.
2. The transcript is the source of truth. Do not invent facts.
3. Strip transcript filler ("uh", "you know", repeated phrases).
4. Do not refer to "the video", "the speaker", "the transcript". Write directly as an authoritative study guide.
5. Output ONLY the markdown content. No preamble. No code-fence wrappers around the whole document.
6. Use ASCII punctuation only. Write `->`, `~`, `Rs.`, straight quotes, and ordinary `-`; never use Unicode arrows, `≈`, `₹`, smart quotes, or Unicode dashes.
7. Keep callout titles plain text. Do not put `**bold**`, `_italic_`, or backticks inside the `[!type] Title` portion.

QUALITY FLOOR:
- Preserve concrete numbers, examples, decision rules, formulas, sequences, caveats, and reasoning.
- Include comparison tables and diverse callouts ([!def], [!warning], [!tip], [!example]) generously.
- Write directly. Avoid empty meta-phrases like "is discussed" or "the importance of" when a concrete explanation can be given instead.
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

MARATHON_CHAPTER_SYSTEM = """You are an elite Competitive Examination Author and Subject Master creating an exhaustive, textbook-grade chapter for a Master Study Handbook (targeting SSC CGL, CHSL, CPO, CDS, UPSC, and Banking exams).

DOCUMENT GOAL & DEPTH:
- Target 1,800 to 2,500 words for this specific chapter.
- Do NOT write high-level summaries. Write complete, detailed rules/concepts with logic, mathematical/syntactic formulations, comparison matrices, and error-spotting exam questions.

OUTPUT FORMAT (Valid Markdown):
# Chapter {chap_num}: {chap_title}

## Overview and Core Concepts
<In-depth 2-3 paragraph breakdown explaining the foundational logic, modern testing patterns, and conceptual framework of these concepts>

## Rules and Grammar Formulas
### Rule 1: <Rule/Concept Title>
- **Rule Formulation**: <Clear mathematical/syntax formula, e.g. Subject + Verb + Formula or Event -> Cause -> Consequence>
- **Grammar/Concept Logic**: <Why this rule applies with deep analytical reasoning>
- **Correct vs Incorrect Table**:
| Incorrect Sentence / Trap Scenario | Correct Sentence / Accurate Fact | Explanation of Error / Nuance |
|---|---|---|
| ... | ... | ... |
| ... | ... | ... |

> [!def] Key Grammar Term / Core Definition
> <Clear definition of the underlying term or concept>

> [!warning] Common Exam Trap / Examiner Trick
> <Specific traps examiners set to deceive candidates in competitive tests>

> [!tip] Quick Revision Shortcut / Rule of Thumb
> <High-speed mental shortcut for instant problem solving>

### Rule 2: <Next Rule/Concept Title>
(Repeat same thorough structure with Rule Formulation, Logic, Correct vs Incorrect Table, and Callouts)

### Rule 3: <Next Rule/Concept Title>
...

## Master Comparison and Decision Matrix
| Condition / Trigger | Rule to Apply | Example |
|---|---|---|
| ... | ... | ... |
| ... | ... | ... |
| ... | ... | ... |
| ... | ... | ... |

## Exam Practice and Solved Examples
> [!example] Solved Exam Problem 1
> **Sentence / Question**: <Sentence with underlined error or multiple choice question>
> **Analysis**: <Detailed step-by-step grammatical/historical reason>
> **Correct Version**: <Corrected formulation>

> [!example] Solved Exam Problem 2
> **Sentence / Question**: <Sentence with underlined error>
> **Analysis**: <Detailed step-by-step grammatical/historical reason>
> **Correct Version**: <Corrected formulation>

> [!example] Solved Exam Problem 3
> **Sentence / Question**: <Sentence with underlined error>
> **Analysis**: <Detailed step-by-step grammatical/historical reason>
> **Correct Version**: <Corrected formulation>

## Chapter Summary: Revise in 60 Seconds
- <Key takeaway 1>
- <Key takeaway 2>
- <Key takeaway 3>
- <Key takeaway 4>
- <Key takeaway 5>

RULES:
1. Ground all explanations strictly in the transcript chunks.
2. Maintain strict ASCII markdown syntax (`->` instead of unicode arrows, standard hyphens and quotes).
3. Do not refer to "the video", "the lecture", "the speaker". Write directly as an authoritative textbook.
4. Output ONLY the chapter markdown. No preamble, no code-fence wrappers.
"""




# === opt-in feature snippets ================================================
# Each entry below is appended to the base system prompt ONLY when the user
# toggled that feature on. The PDF builder parses the resulting markdown and
# renders the new bits — see scripts/build_illustrated_book.py and
# scripts/build_cheatsheet.py.
#
# Keep each snippet small (token budget) and self-contained (no cross-refs).
# When a snippet exists for both kinds, the text differs slightly so the LLM
# adapts the formality to the document shape.

_SNIPPET_SUMMARY = """SUMMARY CARD — Add an HTML-comment-delimited block at the start of the document. **This block IS part of the required output — emit it even though the base prompt asks for "no preamble". The renderer parses these HTML comments as machine-readable metadata, not as prose preamble.**

Place it AT THE VERY TOP, BEFORE the `#` title line. Exact shape:

<!--SUMMARY-->
- **TL;DR:** <one sentence — what this is, in plain English>
- **3 takeaways:**
  1. <first key insight, ~10 words>
  2. <second key insight, ~10 words>
  3. <third key insight, ~10 words>
- **Difficulty:** Beginner | Intermediate | Advanced
- **Read time:** ~N min
<!--/SUMMARY-->

# <title — the existing skeleton continues here>

The renderer extracts this block and prints it as a styled summary card; you do NOT need to repeat the same info inside the body."""

_SNIPPET_TLDR_CHEAT = """TLDR CALLOUTS — At the START of each numbered `## N. ...` section, add a one-line takeaway as a callout:

> [!tldr]
> <one sentence — the key takeaway of this section>

These help readers skim. Don't pad. If the section's title already says it all, skip the callout for that section."""

_SNIPPET_TLDR_BOOK = """TLDR CALLOUTS — At the START of each `## Chapter N — ...` section (before the "Why this chapter matters" subsection), add a one-line takeaway as a callout:

> [!tldr]
> <one sentence — the chapter's key insight>

These complement (don't replace) the existing `> [!revise]` recap at the end of each chapter — the `[!tldr]` is a forecast, the `[!revise]` is a recap."""

_SNIPPET_QNA = """SELF-TEST APPENDIX — At the VERY END of the document (after the Glossary if one exists), add this section:

## Self-Test

> [!q] <Question 1 — tests understanding, not rote recall>
> A: <One-paragraph answer that explains, not just states>

> [!q] <Question 2>
> A: <answer>

(Aim for 5-8 questions covering the main concepts. Each Q&A is one `> [!q]` callout. Frame questions like "Why does X work?" / "When would you use Y?" / "How does X differ from Y?" — not "What does X stand for?")"""

_SNIPPET_MERMAID = """DIAGRAM CODE — Add ONE mindmap and (if the topic has a clear process) ONE flowchart as fenced code blocks with the `mermaid` language tag:

```mermaid
mindmap
  root((<central topic, 1-3 words>))
    <Theme A>
      <sub-point>
      <sub-point>
    <Theme B>
      <sub-point>
```

```mermaid
flowchart TD
  A[Start] --> B{Decision}
  B -->|Yes| C[Path 1]
  B -->|No| D[Path 2]
```

Placement: just before the Glossary (or at the very end if no Glossary). Emit the fenced blocks DIRECTLY — **do NOT add a `## Diagrams` (or similar) section heading above them.** The renderer auto-labels each diagram with its own caption ("Concept mindmap" / "Process flowchart"), and a standalone heading visually orphans on the previous page when the diagram pushes to a new one.

Keep node labels SHORT (≤4 words each) — long labels truncate in the rendered image. If the topic is purely narrative and has no decision points, output the mindmap only and skip the flowchart. The PDF renderer converts each fenced block to an embedded diagram image."""

CHEATSHEET_FEATURE_SNIPPETS: dict[str, str] = {
    "summary": _SNIPPET_SUMMARY,
    "tldr":    _SNIPPET_TLDR_CHEAT,
    "qna":     _SNIPPET_QNA,
    "mermaid": _SNIPPET_MERMAID,
    "chapters": "",   # PDF-only; renderer scans existing headings + adds QR
}

BOOK_FEATURE_SNIPPETS: dict[str, str] = {
    "summary": _SNIPPET_SUMMARY,
    "tldr":    _SNIPPET_TLDR_BOOK,
    "qna":     _SNIPPET_QNA,
    "mermaid": _SNIPPET_MERMAID,
    "chapters": "",   # PDF-only; renderer scans `## Chapter N` + adds QR
}


def _compose_system_prompt(
    base: str,
    snippets: dict[str, str],
    features: list[str] | None,
) -> str:
    """Append opt-in feature instructions to the base system prompt.

    Snippets are concatenated in the order they appear in ``features`` (the
    caller should pass an already-canonicalised list from
    ``cache.normalize_features`` so ordering is stable across submissions).
    Empty snippets are skipped — that's how PDF-only features like
    ``chapters`` declare "I don't need anything from the LLM".
    """
    if not features:
        return base
    extras = [s for f in features if (s := snippets.get(f))]
    if not extras:
        return base
    return (
        f"{base}\n\n"
        "---\n\n"
        "ADDITIONAL OPT-IN OUTPUTS — the user requested the following "
        "extras. Include each in the markdown exactly as instructed:\n\n"
        + "\n\n".join(extras)
    )


CHUNK_RE = re.compile(r"^##\s+Chunk\s+\d+", re.MULTILINE)
TPM_LIMIT_TOKENS = 8000    # qwen/qwen3.6-27b free-tier request/TPM ceiling
FINAL_BODY_BUDGET_TOKENS = 2400
INTER_CALL_DELAY_S = 25    # several transcript chunks must share one TPM window


# --- post-processing ---------------------------------------------------------

_SUMMARY_BLOCK_RE = re.compile(
    r"<!--\s*SUMMARY\s*-->.*?<!--\s*/SUMMARY\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def strip_wrappers(md: str) -> str:
    """Remove preamble lines and outer code fences the model sometimes adds.

    The preamble-strip ("delete everything before the first ``#``") is great
    for catching the "Here is the cheatsheet:" boilerplate models like to
    add, but it also nukes the opt-in `<!--SUMMARY-->` block when the model
    correctly places it above the title (per the SUMMARY snippet in
    author.py). We pull that block out FIRST, run the preamble strip
    normally, then re-prepend it so the PDF builder can still find it.
    """
    md = md.strip()
    # Strip outer ```markdown ... ``` fence
    if md.startswith("```"):
        first_nl = md.find("\n")
        if first_nl != -1:
            md = md[first_nl + 1:]
        if md.endswith("```"):
            md = md[:-3]
        md = md.strip()
    # Preserve the SUMMARY block across the preamble strip below.
    summary_match = _SUMMARY_BLOCK_RE.search(md)
    summary_block = ""
    if summary_match:
        summary_block = summary_match.group(0)
        md = md[:summary_match.start()] + md[summary_match.end():]
    # Strip "Here is the..." preamble before the first heading
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#"):
            md = "\n".join(lines[i:])
            break
    md = md.replace("→", "->").strip() + "\n"
    if summary_block:
        md = summary_block + "\n\n" + md
    return md


def _strip_reasoning(md: str) -> str:
    """Remove reasoning text if a reasoning model emits it despite settings."""
    return re.sub(r"<think>.*?</think>\s*", "", md, flags=re.DOTALL).strip()


# --- providers ---------------------------------------------------------------

def _author_groq(system: str, user: str, *, max_tokens: int = 8000,
                 cost_sink: Optional[dict] = None) -> str:
    # Groq Llama 3.3 70B Versatile supports up to 128k context with 30k TPM.
    # Trim or summarize if user message is exceptionally huge.
    prompt_tokens = est_tokens(system) + est_tokens(user)
    if prompt_tokens > 25000:
        # Emergency trim to fit inside Groq window
        user = user[:75000]
        prompt_tokens = est_tokens(system) + est_tokens(user)

    request_max_tokens = min(max_tokens, 8000)
    from bot.config import GROQ_API_KEY, GROQ_API_KEYS
    keys_pool = list(dict.fromkeys(GROQ_API_KEYS or [GROQ_API_KEY]))
    from groq import Groq
    
    # Active Groq models on user account
    models = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "groq/compound", "openai/gpt-oss-20b"]
    for api_k in keys_pool:
        client = Groq(api_key=api_k)
        for model in models:
            # For 8k TPM models, keep prompt under 6000 tokens to avoid 413
            if model in ("qwen/qwen3.6-27b", "openai/gpt-oss-20b"):
                model_user = user[:18000] if len(user) > 18000 else user
            else:
                model_user = user

            model_options = {}
            if model.startswith("qwen/"):
                model_options = {
                    "reasoning_effort": "none",
                    "reasoning_format": "hidden",
                }
            for attempt in range(1, 3):
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": model_user},
                        ],
                        temperature=0.3,
                        max_tokens=request_max_tokens,
                        **model_options,
                    )

                    text = _strip_reasoning(resp.choices[0].message.content or "")
                    if not text:
                        raise RuntimeError("Groq returned an empty authoring response")
                    if cost_sink is not None:
                        cost_sink["authoring_model"] = model
                        if getattr(resp, "usage", None):
                            cost_sink["tokens_in"] = (
                                cost_sink.get("tokens_in", 0)
                                + int(resp.usage.prompt_tokens or 0)
                            )
                            cost_sink["tokens_out"] = (
                                cost_sink.get("tokens_out", 0)
                                + int(resp.usage.completion_tokens or 0)
                            )
                    return text
                except Exception as exc:
                    last_err = exc
                    error_text = str(exc).casefold()
                    if any(tok in error_text for tok in ("rate limit", "429", "quota", "too large")):
                        print(f"[author] groq model {model!r} rate limited on key ...{api_k[-6:]}; rotating", flush=True)
                        break
                    wait = 3 * attempt
                    time.sleep(wait)
    raise RuntimeError(f"All Groq fallback models and keys failed. Last error: {last_err}")


def _author_ollama(system: str, user: str, *, max_tokens: int = 8000,
                   cost_sink: Optional[dict] = None) -> str:
    """Author through the local Ollama HTTP API; no cloud key is required."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    prompt_tokens = est_tokens(system) + est_tokens(user) + 96
    num_ctx = max(8192, min(32768, prompt_tokens + max_tokens + 1024))
    payload = json.dumps({
        "model": AUTHORING_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": max_tokens,
            "num_ctx": num_ctx,
        },
    }).encode("utf-8")
    request = Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_err = None
    for attempt in range(1, 3):
        try:
            with urlopen(request, timeout=900) as response:
                result = json.loads(response.read().decode("utf-8"))
            text = _strip_reasoning(
                ((result.get("message") or {}).get("content") or "")
            )
            if not text:
                raise RuntimeError("Ollama returned an empty authoring response")
            if cost_sink is not None:
                cost_sink["tokens_in"] = (
                    cost_sink.get("tokens_in", 0)
                    + int(result.get("prompt_eval_count") or prompt_tokens)
                )
                cost_sink["tokens_out"] = (
                    cost_sink.get("tokens_out", 0)
                    + int(result.get("eval_count") or est_tokens(text))
                )
            return text
        except (HTTPError, URLError, TimeoutError, OSError, ValueError,
                RuntimeError) as exc:
            last_err = exc
            if attempt < 2:
                print(
                    f"[author] ollama attempt {attempt}/2 failed: {exc}; "
                    "waiting 3s",
                    flush=True,
                )
                time.sleep(3)
    raise RuntimeError(
        "Local Ollama authoring failed. Ensure Ollama is running and model "
        f"{AUTHORING_MODEL!r} is installed. Last error: {last_err}"
    )


class ClaudeCodeUnrecoverableError(RuntimeError):
    """Raised when claude CLI fails in a way that retrying inside the 11-minute
    backoff window won't help — auth expired, quota hit, account suspended.
    Distinct so ``_author`` can immediately fall back to Groq instead of
    burning ~11 minutes on doomed retries."""


# Kept as an alias for backwards compatibility with any external code that
# imported the old name. Internal callers should use the new one.
ClaudeCodeAuthError = ClaudeCodeUnrecoverableError


class CodexCliUnrecoverableError(RuntimeError):
    """Codex CLI cannot recover without sign-in or a quota reset."""


def _should_fallback_from_claude(stdout: str, stderr: str) -> bool:
    """Heuristic: does this CLI failure look like a 'won't recover in 11 min'
    error, where retrying with backoff is hopeless and we should fail fast +
    fall back to Groq instead?

    Covers two categories:
      - **Auth errors** (HTTP 401, invalid credentials, missing token).
        Retrying won't fix a dead OAuth token; only a human re-auth will.
      - **Quota / rate-limit errors** (e.g. "You've hit your limit ·
        resets 10:50pm (UTC)" on the Max plan). The reset is hours away;
        the user's job needs an answer now, so the Groq backstop is better
        than 11 min of doomed retries followed by a hard fail.

    Genuine transient errors (network blip, brief 5xx, timeout) are
    deliberately NOT caught here — the existing 60s+600s backoff loop is
    the right behaviour for those.
    """
    blob = f"{stdout} {stderr}".lower()
    # Auth-style failures
    if (
        ("401" in blob and ("authenticate" in blob or "credentials" in blob))
        or "invalid_api_key" in blob
        or "invalid authentication" in blob
        or "invalid refresh token" in blob
        or "access token could not be refreshed" in blob
        or "authentication token is expired" in blob
        or "token_expired" in blob
        or "log out and sign in again" in blob
    ):
        return True
    # Quota / usage-cap failures. The Max plan's message is very stable:
    # "You've hit your limit · resets HH:MMpm (UTC)". Match on the most
    # specific phrases first, then more general fallbacks.
    if "hit your limit" in blob or "usage limit" in blob:
        return True
    if "rate limit" in blob and ("reset" in blob or "exceeded" in blob):
        return True
    if "quota" in blob and "exceeded" in blob:
        return True
    return False


# Kept for callers that imported the old narrow predicate. New code should
# use _should_fallback_from_claude.
_is_claude_auth_error = _should_fallback_from_claude


def _author_claude_code(system: str, user: str, *, max_tokens: int = 8000,
                        cost_sink: Optional[dict] = None) -> str:
    """Invoke the Claude Code CLI in headless print mode.

    Bills against the user's Max subscription, not the API. The CLI must be
    logged in on the host (run `claude` interactively once to set up auth).
    The full prompt is piped via stdin to avoid command-line length limits.

    Retries: 3 attempts. The first retry waits 60s (transient blip); the
    second waits 600s (10 min) — long enough to clear most Max-plan rate
    windows. Each attempt captures BOTH stdout and stderr so the surfaced
    error reveals whether it was a rate limit, auth issue, etc.

    Auth errors short-circuit the retry loop and raise ``ClaudeCodeAuthError``
    on the FIRST attempt — no point waiting 11 minutes for the OAuth token
    to un-expire. The caller (``_author``) catches this and may fall back
    to Groq.
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
                # CLI doesn't report tokens; estimate from char counts so the
                # admin dashboard at least sees a directional number.
                if cost_sink is not None:
                    cost_sink["tokens_in"] = (
                        cost_sink.get("tokens_in", 0) + est_tokens(full_prompt)
                    )
                    cost_sink["tokens_out"] = (
                        cost_sink.get("tokens_out", 0) + est_tokens(res.stdout)
                    )
                return res.stdout
            # Failure path — gather everything we have to surface upstream.
            stdout = (res.stdout or "").strip()
            stderr = (res.stderr or "").strip()
            if _should_fallback_from_claude(stdout, stderr):
                # Fast-fail: retries inside the next 11 min won't help an
                # expired OAuth token or a rate-limit window that resets
                # hours away. Caller should fall back to Groq.
                print(f"[author] claude CLI unrecoverable (no retry): "
                      f"stdout={stdout[:200]!r}", flush=True)
                raise ClaudeCodeUnrecoverableError(
                    f"Claude CLI unrecoverable: {stdout[:200]}"
                )
            last_msg = (f"exit={res.returncode} "
                        f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}")
        except ClaudeCodeUnrecoverableError:
            raise  # bubble up immediately, skip retry loop
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


def _author_codex_cli(system: str, user: str, *, max_tokens: int = 8000,
                      cost_sink: Optional[dict] = None) -> str:
    """Invoke Codex CLI non-interactively and capture only its final message.

    The transcript is untrusted input, so Codex runs in a fresh temporary
    directory with a read-only sandbox and no project instructions. The child
    environment intentionally omits application/API secrets; HOME and
    CODEX_HOME remain available only so the CLI can use its own login.
    """
    import os
    import subprocess
    import tempfile

    del max_tokens  # Codex CLI owns its completion budget.
    full_prompt = (
        "Return only the requested Markdown document. Do not inspect files, "
        "run commands, or discuss your process.\n\n"
        f"{system}\n\n---\n\n{user}"
    )
    child_env = {
        key: value
        for key in (
            "HOME",
            "PATH",
            "LANG",
            "LC_ALL",
            "TERM",
            "CODEX_HOME",
            "SSL_CERT_FILE",
        )
        if (value := os.environ.get(key))
    }
    last_msg = ""

    for attempt in range(1, 3):
        with tempfile.TemporaryDirectory(prefix="cheetsheet-codex-") as temp_dir:
            output_path = Path(temp_dir) / "last-message.md"
            cmd = [
                CODEX_CLI_BIN,
                "exec",
                "--ephemeral",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-C",
                temp_dir,
                "-o",
                str(output_path),
                "-",
            ]
            try:
                res = subprocess.run(
                    cmd,
                    input=full_prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=900,
                    env=child_env,
                )
                stdout = (res.stdout or "").strip()
                stderr = (res.stderr or "").strip()
                text = (
                    output_path.read_text(encoding="utf-8", errors="replace").strip()
                    if output_path.exists()
                    else ""
                )
                if res.returncode == 0 and text:
                    if cost_sink is not None:
                        cost_sink["tokens_in"] = (
                            cost_sink.get("tokens_in", 0) + est_tokens(full_prompt)
                        )
                        cost_sink["tokens_out"] = (
                            cost_sink.get("tokens_out", 0) + est_tokens(text)
                        )
                    return _strip_reasoning(text)
                if _should_fallback_from_claude(stdout, stderr):
                    raise CodexCliUnrecoverableError(
                        "Codex CLI login or quota is unavailable"
                    )
                last_msg = (
                    f"exit={res.returncode} stdout={stdout[:240]!r} "
                    f"stderr={stderr[:240]!r}"
                )
            except CodexCliUnrecoverableError:
                raise
            except FileNotFoundError as exc:
                raise CodexCliUnrecoverableError(
                    f"Codex CLI executable was not found: {exc}"
                ) from exc
            except subprocess.TimeoutExpired:
                last_msg = "timed out after 900s"
            except Exception as exc:
                last_msg = f"{type(exc).__name__}: {exc}"

        print(
            f"[author] codex CLI attempt {attempt}/2 failed: {last_msg}",
            flush=True,
        )
        if attempt < 2:
            time.sleep(30)

    raise RuntimeError(
        f"Codex CLI authoring failed after 2 attempts. Last error: {last_msg}"
    )


def _author_gemini(system: str, user: str, *, max_tokens: int = 8000,
                   cost_sink: Optional[dict] = None) -> str:
    """Invoke the Gemini API directly via HTTP request with fallback models."""
    import requests
    import time
    from bot.config import GEMINI_API_KEY, GEMINI_API_KEYS, AUTHORING_MODEL
    
    primary_model = AUTHORING_MODEL
    if not primary_model.startswith("gemini-"):
        primary_model = "gemini-3.6-flash"
        
    models_to_try = [
        primary_model,
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-flash-latest",
        "gemini-pro-latest",
        "gemini-3.7-flash",
        "gemini-3.1-flash-lite"
    ]
    models_to_try = list(dict.fromkeys(models_to_try))
    
    keys_to_try = list(dict.fromkeys(GEMINI_API_KEYS or [GEMINI_API_KEY]))


    last_err = None
    for api_key in keys_to_try:
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": user}]
                    }
                ],
                "systemInstruction": {
                    "parts": [{"text": system}]
                },
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.3
                }
            }
            
            headers = {"Content-Type": "application/json"}
            
            for attempt in range(1, 3):
                try:
                    resp = requests.post(url, json=payload, headers=headers, timeout=120)
                    if resp.status_code == 200:
                        data = resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if not text:
                            raise RuntimeError("Gemini returned an empty response")
                            
                        if cost_sink is not None:
                            cost_sink["authoring_model"] = model
                            usage = data.get("usageMetadata", {})
                            cost_sink["tokens_in"] = (
                                cost_sink.get("tokens_in", 0) + int(usage.get("promptTokenCount", 0))
                            )
                            cost_sink["tokens_out"] = (
                                cost_sink.get("tokens_out", 0) + int(usage.get("candidatesTokenCount", 0))
                            )
                        return text
                    elif resp.status_code in (404, 503, 429):
                        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
                    else:
                        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
                except Exception as exc:
                    last_err = exc
                    error_msg = str(exc).casefold()
                    
                    # Fall over immediately to next model or next API key for rate limits or unavailable errors
                    if any(err_token in error_msg for err_token in ("404", "503", "429", "resource_exhausted", "quota", "not found", "unavailable")):
                        print(f"[author] gemini {model} (key ...{api_key[-6:]}) rate limited or unavailable ({exc}); rotating key/model immediately", flush=True)
                        break
                        
                    wait = 3 * attempt
                    print(f"[author] gemini {model} attempt {attempt}/2 failed: {exc}; waiting {wait}s", flush=True)
                    if attempt < 2:
                        time.sleep(wait)
            else:
                continue
                
    raise RuntimeError(f"Gemini authoring failed across {len(keys_to_try)} API keys and {len(models_to_try)} models. Last error: {last_err}")




def _author(system: str, user: str, *, max_tokens: int = 8000,
            cost_sink: Optional[dict] = None) -> str:
    """Dispatch to the configured authoring provider."""
    if AUTHORING_PROVIDER == "groq":
        return _author_groq(system, user, max_tokens=max_tokens, cost_sink=cost_sink)
    if AUTHORING_PROVIDER == "gemini":
        try:
            return _author_gemini(
                system, user, max_tokens=max_tokens, cost_sink=cost_sink
            )
        except Exception as exc:
            if GROQ_API_KEY:
                print(f"[author] gemini failed ({exc}); falling back to groq llama/qwen immediately", flush=True)
                if cost_sink is not None:
                    cost_sink["fallback_used"] = "groq"
                    cost_sink["fallback_reason"] = "gemini_error"
                return _author_groq(
                    system, user, max_tokens=max_tokens, cost_sink=cost_sink
                )
            raise

    if AUTHORING_PROVIDER == "ollama":
        return _author_ollama(
            system, user, max_tokens=max_tokens, cost_sink=cost_sink
        )
    if AUTHORING_PROVIDER == "codex_cli":
        try:
            return _author_codex_cli(
                system, user, max_tokens=max_tokens, cost_sink=cost_sink
            )
        except CodexCliUnrecoverableError as exc:
            if GROQ_API_KEY:
                print(
                    f"[author] codex CLI unavailable; falling back to groq: {exc}",
                    flush=True,
                )
                if cost_sink is not None:
                    cost_sink["fallback_used"] = "groq"
                    cost_sink["fallback_reason"] = "codex_cli_unrecoverable"
                return _author_groq(
                    system, user, max_tokens=max_tokens, cost_sink=cost_sink
                )
            raise
    if AUTHORING_PROVIDER == "claude_code":
        try:
            return _author_claude_code(
                system, user, max_tokens=max_tokens, cost_sink=cost_sink
            )
        except ClaudeCodeUnrecoverableError as exc:
            if GROQ_API_KEY:
                print(
                    f"[author] claude unrecoverable; falling back to groq: {exc}",
                    flush=True,
                )
                if cost_sink is not None:
                    cost_sink["fallback_used"] = "groq"
                    cost_sink["fallback_reason"] = "claude_code_unrecoverable"
                return _author_groq(
                    system, user, max_tokens=max_tokens, cost_sink=cost_sink
                )
            raise  # no GROQ_API_KEY configured — let the error bubble
    raise NotImplementedError(
        f"AUTHORING_PROVIDER={AUTHORING_PROVIDER!r} not wired yet — switch to "
        "'ollama' / 'groq' / 'codex_cli' / 'claude_code' or extend bot/author.py"
    )


def _needs_condensation() -> bool:
    """Return True if the active provider has tight TPM limits (forcing map-reduce)."""
    if AUTHORING_PROVIDER in {"groq", "ollama"}:
        return True
    if AUTHORING_PROVIDER == "gemini":
        return False
    # CLI providers can accept the full transcript, but their automatic Groq
    # backstop cannot. Pre-condense while that fallback is configured so an
    # expired CLI login never converts a valid transcript into an oversized
    # emergency request.
    return (
        AUTHORING_PROVIDER in {"codex_cli", "claude_code"}
        and bool(GROQ_API_KEY)
    )



def _cheatsheet_quality_issues(
    markdown: str, duration_seconds: Optional[float]
) -> list[str]:
    """Return structural reasons a substantive cheatsheet is too lightweight."""
    if not duration_seconds or duration_seconds < 8 * 60:
        return []

    issues: list[str] = []
    word_count = len(re.findall(r"\b\w+[\w'-]*\b", markdown))
    minimum_words = 650 if duration_seconds < 15 * 60 else 800
    if word_count < minimum_words:
        issues.append(f"only {word_count} words")
    if not re.search(r"(?m)^\s*\|.+\|\s*$\n\s*\|\s*:?-{3,}", markdown):
        issues.append("no useful markdown table")
    if markdown.count("> [!") < 3:
        issues.append("fewer than three callouts")
    return issues


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
    # Reserve room for instructions, response, and API message overhead.
    chunk_budget = TPM_LIMIT_TOKENS - 1200
    chunks = split_transcript(transcript, chunk_budget)
    if len(chunks) == 1 and est_tokens(chunks[0]) < chunk_budget - 1500:
        # Already small enough — no condensation needed.
        return chunks[0]

    summaries: list[str] = []
    for i, c in enumerate(chunks, 1):
        if on_progress:
            on_progress(f"Summarising chunk {i}/{len(chunks)}...")
        # 300 tokens regularly collapsed an eight-minute transcript chunk to
        # a handful of generic bullets. 600 still keeps map-reduce bounded but
        # preserves enough names, numbers, caveats, and causal reasoning for a
        # substantial final document.
        s = _author(SUMMARISE_SYSTEM, c, max_tokens=600)
        summaries.append(f"### Section {i}\n{s.strip()}")
        if i < len(chunks) and AUTHORING_PROVIDER == "groq":
            time.sleep(INTER_CALL_DELAY_S)
    combined = "\n\n".join(summaries)
    if est_tokens(combined) <= FINAL_BODY_BUDGET_TOKENS:
        return combined

    # A long recording can yield individually valid summaries whose combined
    # size still makes the final document request invalid. Run one bounded
    # reduce pass so authoring always receives a predictable-size source.
    if on_progress:
        on_progress("Combining section summaries...")
    reduce_system = """Condense the supplied section summaries into a single,
information-dense markdown outline. Preserve names, numbers, examples,
comparisons, causal reasoning, caveats, and recommendations. Remove repetition.
Use short headings and bullets only. Do not add facts or a preamble."""
    reduced = _author(reduce_system, combined, max_tokens=1800)
    if est_tokens(reduced) > FINAL_BODY_BUDGET_TOKENS:
        # This is a final safety valve for providers that ignore max_tokens.
        reduced = reduced[:FINAL_BODY_BUDGET_TOKENS * 3]
    return reduced


def author_marathon_handbook(transcript: str, *, title_hint: Optional[str] = None,
                             duration_seconds: Optional[float] = None,
                             on_progress: ProgressFn = None,
                             cost_sink: Optional[dict] = None) -> str:
    """Generate an exhaustive 25-50 page multi-chapter handbook for long videos (> 2 hours)."""
    # 1. Parse raw or sectioned transcript chunks
    raw_chunks = split_transcript(transcript, 8000)
    total_chunks = len(raw_chunks)
    if total_chunks <= 1:
        # Fallback to single pass if only 1 chunk
        return ""

    # 2. Determine chapter count: target ~8 to 14 chapters (roughly 3-6 chunks per chapter)
    num_chapters = min(14, max(6, total_chunks // 4))
    chunk_step = max(1, total_chunks // num_chapters)

    main_title = (title_hint or "Comprehensive Course Masterclass Handbook").strip()
    chapters_md: list[str] = []

    for chap_idx in range(num_chapters):
        start_c = chap_idx * chunk_step
        end_c = (chap_idx + 1) * chunk_step if chap_idx < num_chapters - 1 else total_chunks
        chapter_chunks = raw_chunks[start_c:end_c]
        combined_text = "\n\n".join(chapter_chunks)

        chap_num = chap_idx + 1
        if on_progress:
            on_progress(f"Authoring Handbook Chapter {chap_num}/{num_chapters} (chunks {start_c+1}-{end_c})...")

        # Derive chapter title from text snippet or chunk content
        first_line = combined_text.strip().split("\n")[0]
        chap_title_hint = f"Module {chap_num}"
        if "## Chunk" in first_line:
            chap_title_hint = f"Section {chap_num}"

        system_prompt = MARATHON_CHAPTER_SYSTEM.replace("{chap_num}", str(chap_num)).replace("{chap_title}", chap_title_hint)
        user_prompt = f"COURSE TITLE: {main_title}\nCHAPTER: {chap_num}\n\nTRANSCRIPT CHUNKS (detailed lecture content):\n{combined_text}"

        try:
            chap_md = _author(
                system_prompt,
                user_prompt,
                max_tokens=6500,
                cost_sink=cost_sink,
            )
            chap_clean = strip_wrappers(chap_md)
            chapters_md.append(chap_clean)
        except Exception as err:
            print(f"[marathon_chapter_{chap_num}_error] {err}", flush=True)
            # Fallback for this single chapter
            chap_summary = _author(SUMMARISE_SYSTEM, combined_text[:12000], max_tokens=1500, cost_sink=cost_sink)
            chapters_md.append(f"## Chapter {chap_num}: Module {chap_num}\n\n{chap_summary}")

    # 3. Compile Master Markdown Document
    header_block = f"# {main_title}\n\n### Comprehensive Study Handbook - Distilled from a {int(duration_seconds/60) if duration_seconds else 120}-Minute Masterclass\n\n"
    master_text = header_block + "\n\n---\n\n".join(chapters_md)
    return master_text


# --- public API --------------------------------------------------------------

def author_cheatsheet(transcript_path: Path, *, title_hint: Optional[str] = None,
                      duration_seconds: Optional[float] = None,
                      on_progress: ProgressFn = None,
                      system_override: Optional[str] = None,
                      cost_sink: Optional[dict] = None,
                      features: Optional[list[str]] = None) -> str:
    """Return cheatsheet markdown text. Caller writes it to disk.

    ``system_override`` — when set, replaces the default CHEATSHEET_SYSTEM
    prompt (used for per-user custom prompts from the admin portal). When
    overridden, ``features`` snippets are NOT appended — the override is
    treated as the complete instruction.
    ``cost_sink`` — if a dict, is populated with ``tokens_in``/``tokens_out``
    so the caller can record per-generation cost.
    ``features`` — opt-in PDF enhancements (see ``CHEATSHEET_FEATURE_SNIPPETS``).
    Each requested feature appends its instructional snippet to the base
    prompt so the model emits the extra markdown the renderer expects.
    """
    transcript = Path(transcript_path).read_text(encoding="utf-8")

    # Marathon Videos (> 2 hours / 7200 seconds): Route to multi-chapter handbook engine!
    if not system_override and duration_seconds and duration_seconds >= 7200:
        if on_progress:
            on_progress("Detected marathon masterclass (>2h). Initializing multi-chapter handbook engine...")
        handbook_md = author_marathon_handbook(
            transcript,
            title_hint=title_hint,
            duration_seconds=duration_seconds,
            on_progress=on_progress,
            cost_sink=cost_sink,
        )
        if handbook_md and len(handbook_md.strip()) > 3000:
            return handbook_md

    if _needs_condensation() or est_tokens(transcript) > 200000:
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
    base_prompt = system_override or CHEATSHEET_SYSTEM
    # Don't decorate user-supplied overrides — they're treated as complete.
    full_prompt = (
        base_prompt if system_override
        else _compose_system_prompt(base_prompt, CHEATSHEET_FEATURE_SNIPPETS, features)
    )
    # Dynamically scale LLM token budget based on video duration
    dur_m = (duration_seconds / 60.0) if duration_seconds else 15.0
    if dur_m <= 30.0:
        base_budget = 3500
    elif dur_m <= 90.0:
        base_budget = 5000
    else:
        base_budget = 7000

    max_out = base_budget + (1500 if features else 0)
    raw = _author(
        full_prompt,
        user_msg,
        max_tokens=max_out,
        cost_sink=cost_sink,
    )

    quality_issues = _cheatsheet_quality_issues(raw, duration_seconds)
    if quality_issues:
        if on_progress:
            on_progress("Expanding a lightweight first draft...")
        repair_system = full_prompt + """

QUALITY REPAIR - REPLACE THE FIRST DRAFT COMPLETELY:
The first draft failed the required density/structure checks. Produce a richer
replacement using only facts supported by the source. Add concrete detail,
decision rules, examples, at least one useful table, and at least three varied
callouts. Do not pad with generic prose and do not define garbled terms.
"""
        repair_user = (
            user_msg
            + "\n\nFIRST DRAFT (replace, do not merely comment on it):\n"
            + raw
            + "\n\nFAILED CHECKS: "
            + "; ".join(quality_issues)
        )
        raw = _author(
            repair_system,
            repair_user,
            max_tokens=max_out,
            cost_sink=cost_sink,
        )
    cleaned = strip_wrappers(raw)
    if not any(line.lstrip().startswith("#") for line in cleaned.splitlines()):
        title = (title_hint or "Cheatsheet Summary").replace('\n', ' ').strip()
        cleaned = f"# {title}\n\n### distilled from video walkthrough\n\n{cleaned}"
    return cleaned


def author_book(transcript_path: Path, frames_index_path: Path, *,
                title_hint: Optional[str] = None,
                duration_seconds: Optional[float] = None,
                on_progress: ProgressFn = None,
                system_override: Optional[str] = None,
                cost_sink: Optional[dict] = None,
                features: Optional[list[str]] = None) -> str:
    """Return illustrated-book markdown. Caller writes it and renders the PDF.

    Same ``system_override`` / ``cost_sink`` / ``features`` semantics as
    :func:`author_cheatsheet`.
    """
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
    base_prompt = system_override or BOOK_SYSTEM
    full_prompt = (
        base_prompt if system_override
        else _compose_system_prompt(base_prompt, BOOK_FEATURE_SNIPPETS, features)
    )
    # Books already get a generous 8K — bump by 2K when features are on so
    # the Q&A appendix + mermaid + summary block don't run out of room on
    # longer chapters.
    max_out = 8000 + (2000 if features else 0)
    raw = _author(
        full_prompt,
        user_msg,
        max_tokens=max_out,
        cost_sink=cost_sink,
    )
    cleaned = strip_wrappers(raw)
    if not any(line.lstrip().startswith("#") for line in cleaned.splitlines()):
        title = (title_hint or "Illustrated Book Notes").replace('\n', ' ').strip()
        cleaned = f"# {title}\n\n### distilled from video walkthrough\n\n{cleaned}"
    return cleaned


MCQ_SYSTEM = """You are an expert Examination Master creating a comprehensive Solved Multiple Choice Question (MCQ) & PYQ Handbook from a lecture transcript.

OUTPUT FORMAT (Valid Markdown):
# <Course / Subject Title> - Solved MCQs & PYQ Bank

## Executive Concept & Formula Summary
<Key concepts, definitions, and formulas needed for solving these questions>

## Question 1: <Short Topic Title>
> Target Exam: Relevant Competitive Exam | Difficulty: Medium

**Q.** <Complete, clear question statement>

- **(A)** <Option A>
- **(B)** <Option B>
- **(C)** <Option C>
- **(D)** <Option D>

> [!correct] (B) <Option Text>
> **Direct Explanation**: <Why B is strictly correct with formulas or rules>
> **Option Elimination**:
> - **(A)** <Why A is incorrect>
> - **(C)** <Why C is incorrect>
> - **(D)** <Why D is incorrect>

> [!tip] Shortcut / Elimination Rule
> <Mental trick for solving in under 30 seconds>

---

## Question 2: ...

RULES:
1. Ground all questions and options strictly in the lecture transcript.
2. Use ASCII punctuation only (`->`, `~`, `-`).
3. Output ONLY valid markdown. No preamble.
"""


def author_mcq(transcript_path: Path, *, title_hint: Optional[str] = None,
               duration_seconds: Optional[float] = None,
               on_progress: ProgressFn = None,
               system_override: Optional[str] = None,
               cost_sink: Optional[dict] = None,
               features: Optional[list[str]] = None) -> str:
    """Return MCQ handbook markdown text."""
    transcript = Path(transcript_path).read_text(encoding="utf-8")
    if _needs_condensation() or est_tokens(transcript) > 200000:
        body = condense(transcript, on_progress=on_progress)
    else:
        body = transcript

    user_msg = f"TITLE: {title_hint or 'MCQ Bank'}\n\nTRANSCRIPT:\n{body}"
    if on_progress:
        on_progress("Authoring Solved MCQ Handbook...")

    prompt = system_override or MCQ_SYSTEM
    raw = _author(prompt, user_msg, max_tokens=7500, cost_sink=cost_sink)
    cleaned = strip_wrappers(raw)
    return cleaned

