"""Run Grounded Veracity Checking and Knowledge Enrichment on a markdown file."""
import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.author import enrich_and_verify_notes
from scripts.build_cheatsheet_refined import build as build_cheatsheet_refined


def main():
    parser = argparse.ArgumentParser(description="Enrich and verify markdown notes")
    parser.add_argument("--input", required=True, help="Path to input markdown file")
    parser.add_argument("--transcript", default="", help="Optional path to raw transcript text")
    parser.add_argument(
        "--style",
        choices=["marked", "blended"],
        default="marked",
        help="Enrichment style: 'marked' (default: tags, callouts, and high-yield links) or 'blended' (seamless textbook weave)",
    )
    parser.add_argument("--out-md", default=None, help="Path for output enriched markdown")
    parser.add_argument("--out-pdf", default=None, help="Path for output enriched PDF")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"Error: input file '{in_path}' not found", file=sys.stderr)
        sys.exit(1)

    md_text = in_path.read_text(encoding="utf-8")
    tr_text = Path(args.transcript).read_text(encoding="utf-8") if args.transcript and Path(args.transcript).is_file() else ""

    print(f"Running Veracity & Knowledge Enrichment Pass on {in_path.name} (Style: {args.style})...")
    res = enrich_and_verify_notes(md_text, tr_text, style=args.style)

    report = res.get("veracity_report", {})
    enriched_md = res.get("enriched_markdown", md_text)

    print("\n--- VERACITY REPORT ---")
    print(f"Verified Facts Count: {report.get('verified_count', 0)}")
    corrections = report.get("corrections", [])
    print(f"Corrections ({len(corrections)}):")
    for c in corrections:
        print(f"  * [{c.get('topic')}] {c.get('spoken_claim')} -> {c.get('corrected_fact')} ({c.get('reason')})")

    enrichments = report.get("enrichments", [])
    print(f"\nEnrichments ({len(enrichments)}):")
    for e in enrichments:
        print(f"  * [{e.get('topic')}] {e.get('added_point')} ({e.get('context')})")

    out_md = Path(args.out_md) if args.out_md else in_path.parent / f"{in_path.stem}_enriched.md"
    out_md.write_text(enriched_md, encoding="utf-8")
    print(f"\nSaved Enriched Markdown to: {out_md}")

    rep_file = out_md.parent / "veracity_report.json"
    rep_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved Veracity Report JSON to: {rep_file}")

    if args.out_pdf:
        out_pdf = Path(args.out_pdf)
        build_cheatsheet_refined(out_md, out_pdf, title=out_md.stem.replace("_", " ").title())
        print(f"Rendered Enriched PDF to: {out_pdf}")


if __name__ == "__main__":
    main()
