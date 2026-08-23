import sys
import os
import json
import time
import re
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.author import _author_gemini, _author_groq
from scripts.build_cheatsheet import build as build_cheatsheet

CHAPTERS_CONFIG = [
    {
        "num": 1,
        "title": "Nouns and Uncountable Rules",
        "chunks": (1, 8),
        "focus": "Uncountable nouns (scenery, furniture, luggage, etc.), rules of pluralization, singular/plural noun forms, collective nouns, and exam pitfalls."
    },
    {
        "num": 2,
        "title": "Pronouns and Relative Clauses",
        "chunks": (9, 16),
        "focus": "Cases of pronouns (subjective vs objective), relative pronouns (who vs whom vs that vs which), distributor pronouns (each, either, neither), reciprocal pronouns."
    },
    {
        "num": 3,
        "title": "Adjectives, Quantifiers and Comparisons",
        "chunks": (17, 24),
        "focus": "Degrees of comparison, elder vs older, little vs few, order of adjectives, superlative traps, parallel comparison rules."
    },
    {
        "num": 4,
        "title": "Adverbs and Inversion Patterns",
        "chunks": (25, 32),
        "focus": "Adverb vs Adjective usage, Hard vs Hardly, Late vs Lately, complete inversion vs partial inversion, negative introductory adverbs (Seldom, Rarely, Never, Scarcely)."
    },
    {
        "num": 5,
        "title": "Subject-Verb Agreement Syntax",
        "chunks": (33, 40),
        "focus": "Rules with along with/as well as/together with, neither-nor/either-or, each/every, collective nouns with singular/plural verbs, percentage/fraction agreement."
    },
    {
        "num": 6,
        "title": "Verbs, Non-Finite Verbs and Participles",
        "chunks": (41, 48),
        "focus": "Gerund vs Infinitive vs Bare Infinitive, causative verbs (make, let, have, help), dangling participles, split infinitives, verbs followed by specific non-finites."
    },
    {
        "num": 7,
        "title": "Tenses and Sequence of Tenses",
        "chunks": (49, 56),
        "focus": "Present Perfect vs Simple Past with time markers (since, for, ago, yesterday), Past Perfect sequence (action 1 vs action 2), stative verbs that avoid continuous tense."
    },
    {
        "num": 8,
        "title": "Conditionals and Subjunctive Mood",
        "chunks": (57, 64),
        "focus": "Zero, 1st, 2nd, 3rd conditional formulas, Inversion in conditionals (Had I known..., Were I..., Should you need...), wish/if only past subjunctive."
    },
    {
        "num": 9,
        "title": "Prepositions and Fixed Usages",
        "chunks": (65, 72),
        "focus": "Between vs Among, Beside vs Besides, In vs Into, On vs Upon, fixed prepositions (senior to, abstain from, angry with/at, prevent from), verbs that take NO preposition."
    },
    {
        "num": 10,
        "title": "Conjunctions and Parallelism",
        "chunks": (73, 80),
        "focus": "Correlative conjunctions (not only...but also, neither...nor, both...and), lest...should, although...yet, parallelism rules across conjunctions."
    },
    {
        "num": 11,
        "title": "Active and Passive Voice Transformations",
        "chunks": (81, 88),
        "focus": "Tense changes in passive, modal passives, imperative sentence passives (Let / You are requested), quasi-passive verbs, verbs with two objects."
    },
    {
        "num": 12,
        "title": "Direct and Indirect Speech and Superfluous Expressions",
        "chunks": (89, 96),
        "focus": "Tense shift and pronoun rules in narration, reporting questions, orders, wishes, common superfluous expressions (return back, blunders, final conclusion)."
    }
]

SYSTEM_PROMPT = """You are an expert English Grammar Master and Author compiling a comprehensive, exhaustive handbook chapter for students preparing for competitive exams (SSC CGL, CHSL, CPO, CDS, UPSC).

DOCUMENT GOAL:
Produce an exhaustive, detailed, high-yield chapter. Do NOT write high-level summaries. Write complete, detailed rules with logic, formulas, comparison tables, and examination examples.

OUTPUT SKELETON (Valid Markdown):
# Chapter {chapter_num}: {chapter_title}

## Overview and Core Concepts
<Detailed explanation of why these rules exist and fundamental logic>

## Rules and Grammar Formulas
### Rule {start_rule_num}: <Rule Title>
- **Rule Formulation**: <Clear mathematical/syntax formula>
- **Grammar Logic**: <Why this rule applies>
- **Correct vs Incorrect Table**:
| Incorrect Sentence | Correct Sentence | Explanation of Error |
|---|---|---|
| ... | ... | ... |
| ... | ... | ... |

> [!def] Key Grammar Term
> <Definition>

> [!warning] Common Exam Trap
> <Traps that examiners frequently test in competitive exams>

> [!tip] Quick Revision Shortcut / Rule of Thumb
> <Mental shortcut>

(Include all key rules in this domain with comprehensive explanations and examples)

## Master Comparison and Decision Matrix
| Condition / Trigger | Rule to Apply | Example |
|---|---|---|
| ... | ... | ... |

## Exam Practice and Solved Examples
> [!example] Solved Exam Problem 1
> **Sentence**: <Sentence with underlined error>
> **Analysis**: <Step by step reason>
> **Correct Version**: <Corrected sentence>

## Chapter Summary: Revise in 60 Seconds
- <Key takeaway 1>
- <Key takeaway 2>
- <Key takeaway 3>
- <Key takeaway 4>

RULES:
1. Target comprehensive depth (1,500 to 2,200 words for this chapter).
2. Maintain strict ASCII markdown syntax.
3. Use callouts [!def], [!warning], [!tip], [!example] generously.
"""

def main():
    data_dir = Path("/opt/video-notes-bot/data/preserved_10hr_grammar")
    output_dir = Path("/opt/video-notes-bot/web_work/marathon_10hr_trial")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("[Marathon Builder] Starting multi-chapter compilation for 10-Hour Masterclass...", flush=True)
    
    chapter_mds = []
    
    for cfg in CHAPTERS_CONFIG:
        c_num = cfg["num"]
        c_title = cfg["title"]
        start_c, end_c = cfg["chunks"]
        focus = cfg["focus"]
        
        chapter_file = output_dir / f"chapter_{c_num:02d}.md"
        if chapter_file.is_file() and chapter_file.stat().st_size > 1500:
            print(f"[Marathon Builder] Chapter {c_num} already exists ({chapter_file.stat().st_size} bytes). Reusing...", flush=True)
            chapter_mds.append(chapter_file.read_text(encoding="utf-8"))
            continue
            
        print(f"\n[Marathon Builder] Processing Chapter {c_num}/{len(CHAPTERS_CONFIG)}: {c_title} (Chunks {start_c} to {end_c})...", flush=True)
        
        # Combine chunk texts
        chunk_texts = []
        for i in range(start_c, end_c + 1):
            c_json = data_dir / f"chunk_{i:02d}.json"
            if c_json.is_file():
                try:
                    c_data = json.loads(c_json.read_text(encoding="utf-8"))
                    text = c_data.get("text", "")
                    if text:
                        chunk_texts.append(f"--- Chunk {i} (Timestamp: ~{i*7.5:.1f}m) ---\n{text}")
                except Exception:
                    pass
                    
        combined_transcript = "\n\n".join(chunk_texts)
        if not combined_transcript:
            print(f"[Warning] No transcript found for Chapter {c_num}", flush=True)
            continue
            
        sys_prompt = SYSTEM_PROMPT.format(
            chapter_num=c_num,
            chapter_title=c_title,
            start_rule_num=(c_num - 1) * 8 + 1
        )
        
        user_prompt = f"CHAPTER TOPIC: {c_title}\nSPECIFIC FOCUS AREAS: {focus}\n\nTRANSCRIPT EXCERPT:\n{combined_transcript[:35000]}"
        
        # Author using multi-model fallback
        try:
            print(f"[Marathon Builder] Calling LLM for Chapter {c_num}...", flush=True)
            try:
                content = _author_gemini(sys_prompt, user_prompt, max_tokens=6000)
            except Exception as e:
                print(f"[Marathon Builder] Gemini fallback to Groq: {e}", flush=True)
                content = _author_groq(sys_prompt, user_prompt, max_tokens=6000)
                
            chapter_file.write_text(content, encoding="utf-8")
            print(f"[Marathon Builder] Chapter {c_num} authored successfully! ({len(content)} chars)", flush=True)
            chapter_mds.append(content)
            time.sleep(2)
        except Exception as exc:
            print(f"[Marathon Builder] Failed to author chapter {c_num}: {exc}", flush=True)
            
    # Compile Master Handbook Markdown
    master_lines = [
        "# Complete 100 Golden Rules of English Grammar — 10-Hour Masterclass Handbook",
        "",
        "> **Exhaustive Comprehensive Study Guide and Rule-by-Rule Reference for SSC CGL, CHSL, CPO, CDS and UPSC**",
        "",
        "## Table of Contents",
        ""
    ]
    
    for cfg in CHAPTERS_CONFIG:
        c_num = cfg["num"]
        c_title = cfg["title"]
        anchor = f"chapter-{c_num}"
        master_lines.append(f"{c_num}. [{c_title}](#{anchor})")
        
    master_lines.append("\n---\n")
    
    for idx, (cfg, md_text) in enumerate(zip(CHAPTERS_CONFIG, chapter_mds), start=1):
        c_num = cfg["num"]
        anchor = f"chapter-{c_num}"
        master_lines.append(f"<a id='{anchor}'></a>")
        master_lines.append(md_text.strip())
        master_lines.append("\n\n---\n\n")
        
    final_master_md = output_dir / "Master_100_Rules_Grammar_Handbook.md"
    final_master_md.write_text("\n".join(master_lines), encoding="utf-8")
    print(f"\n[Marathon Builder] Master Markdown compiled: {final_master_md} ({final_master_md.stat().st_size} bytes)", flush=True)
    
    # Render final PDF
    final_master_pdf = output_dir / "Master_100_Rules_Grammar_Handbook.pdf"
    print(f"[Marathon Builder] Rendering Final Comprehensive PDF to: {final_master_pdf}...", flush=True)
    
    build_cheatsheet(
        final_master_md,
        final_master_pdf,
        title="100 Golden Rules of English Grammar — Complete Handbook",
        features=[],
        source_url="https://www.youtube.com/watch?v=2KReO6IElUk"
    )
    
    print(f"\n[Marathon Builder] ? FINISHED! Final PDF rendered successfully: {final_master_pdf} ({final_master_pdf.stat().st_size / 1024:.1f} KB)", flush=True)

if __name__ == "__main__":
    main()
