import unittest
from scripts.build_illustrated_book import parse_blocks as parse_book_blocks, inline as inline_book, _clean_orphaned_markers, _clean_list_item
from scripts.build_cheatsheet import parse_blocks as parse_cs_blocks, inline as inline_cs


class TestMarkdownSanitization(unittest.TestCase):
    def test_clean_orphaned_markers(self):
        # Pure marker noise
        self.assertEqual(_clean_orphaned_markers("**"), "")
        self.assertEqual(_clean_orphaned_markers("***"), "")
        self.assertEqual(_clean_orphaned_markers("* *"), "")
        self.assertEqual(_clean_orphaned_markers("  **  "), "")

        # Lone unclosed bold
        self.assertEqual(_clean_orphaned_markers("**word"), "word")

        # Properly closed bold should remain
        self.assertEqual(_clean_orphaned_markers("**word**"), "**word**")

    def test_clean_list_item(self):
        # Double-dash bullet
        self.assertEqual(_clean_list_item("- Senior judges discuss"), "Senior judges discuss")
        self.assertEqual(_clean_list_item("- **"), "")

    def test_parse_blocks_illustrated_book(self):
        md = """### Rule 4: Doctrine of Judicial Review & Basic Structure  
- **


---

## Chapter 2: Module 2

- - Senior judges discuss appointment of judges
- - Collegium is a closed-room meeting
"""
        blocks = list(parse_book_blocks(md))
        kinds = [b[0] for b in blocks]
        self.assertIn("h3", kinds)
        self.assertIn("hr", kinds)
        self.assertIn("h2", kinds)

        ul_blocks = [b[1] for b in blocks if b[0] == "ul"]
        for ul in ul_blocks:
            for item in ul:
                text = item[1] if isinstance(item, tuple) else item
                self.assertNotEqual(text.strip(), "")
                self.assertNotEqual(text.strip(), "**")
                self.assertFalse(text.startswith("- "))

    def test_inline_empty_handling(self):
        self.assertEqual(inline_book("**"), "")
        self.assertEqual(inline_book("   "), "")
        self.assertEqual(inline_cs("**"), "")

    def test_clean_latex_math_fractions_and_subscripts(self):
        from scripts.build_mcq_handbook import _clean_latex_math as math_mcq
        from scripts.build_cheatsheet import _clean_latex_math as math_cs
        from scripts.build_illustrated_book import _clean_latex_math as math_book
        from scripts.math_typography import sanitize_math_typography

        sample_input = "Formula: Mass_{middle} ≈ frac{Mass_{1st} + Mass_{3rd}}{2}."
        expected_output = "Formula: Mass<sub>middle</sub> ~ (Mass<sub>1st</sub> + Mass<sub>3rd</sub>) / 2."

        for fn in (math_mcq, math_cs, math_book, sanitize_math_typography):
            self.assertEqual(fn(sample_input), expected_output)
            self.assertEqual(fn(r"\frac{a}{b}"), "a / b")
            self.assertEqual(fn(r"frac{1}{2}"), "1 / 2")
            self.assertEqual(fn(r"\dfrac{x + y}{z - w}"), "(x + y) / (z - w)")
            self.assertEqual(fn(r"\approx 10.5"), "~ 10.5")
            self.assertEqual(fn(r"\text{Mass}_{1st}"), "Mass<sub>1st</sub>")
            self.assertEqual(fn(r"\sqrt{x^2 + y^2}"), "√(x<sup>2</sup> + y<sup>2</sup>)")

    def test_math_typography_unified_across_all_builders(self):
        from scripts.build_cheatsheet_refined import clean_inline as ci_refined
        from scripts.build_cheatsheet import inline as inline_cs
        from scripts.build_mcq_handbook import inline as inline_mcq
        from scripts.build_illustrated_book import inline as inline_book
        from scripts.build_structured_notes_style1 import clean_inline as ci_style1
        from scripts.build_structured_notes_style2 import clean_inline as ci_style2
        from scripts.build_structured_notes import clean_inline as ci_sn
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph

        style = getSampleStyleSheet()["Normal"]

        test_cases = [
            r"Rate R\% = x/y implies Multiplier = (y+x)/y",
            r"(P : A)_{Total} = (y)^T : (y+x)^T",
            r"CI_{Units} = (y+x)^T - y^T",
            r"Convert rate R\% into an improper multiplier fraction frac{A_{1}}{P_{1}}.",
            r"left(frac{A_{1}}{P_{1}}right)^t = frac{A_{t}}{P_{t}}.",
            r"Principal Unit (P): Base of the exponentiated fraction (P_1^t).",
            r"Compound Interest Unit (CI): Difference between Amount and Principal units (A_t - P_t).",
            r"left(7/6right)^2 = 49/36",
            r"16\frac{2}{3}\% = 1/6",
            r"x^2 + y^2 = z^2",
            r"CI = 13 units \times 96 = Rs. 1,248",
        ]

        all_cleaners = [
            ci_refined, inline_cs, inline_mcq, inline_book,
            ci_style1, ci_style2, ci_sn
        ]

        for cleaner in all_cleaners:
            for tc in test_cases:
                formatted = cleaner(tc)
                # Verify no raw LaTeX delimiters or commands leak
                self.assertNotIn(r"frac{", formatted, f"Raw frac left in: {formatted}")
                self.assertNotIn(r"left(", formatted, f"Raw left( left in: {formatted}")
                self.assertNotIn(r"right)", formatted, f"Raw right) left in: {formatted}")
                self.assertNotIn(r"\%", formatted, f"Raw \\% left in: {formatted}")
                # Verify ReportLab can parse and construct Paragraph without XML syntax errors
                p = Paragraph(formatted, style)
                self.assertIsNotNone(p)

    def test_callout_palette_white_tint(self):
        from scripts.build_mcq_handbook import CALLOUTS as mcq_co
        from scripts.build_cheatsheet import CALLOUTS as cs_co
        from scripts.build_illustrated_book import CALLOUTS as book_co
        from reportlab.lib import colors

        white = colors.HexColor("#FFFFFF")
        for palette in (mcq_co, cs_co, book_co):
            for kind, spec in palette.items():
                self.assertEqual(spec["tint"], white, f"Callout '{kind}' tint should be pure white #FFFFFF")

    def test_mcq_make_callout_structure(self):
        from scripts.build_mcq_handbook import make_callout
        from reportlab.platypus import Table, KeepTogether

        callout_elems = make_callout("correct", "Option (C)", ["Direct explanation line."])
        tables = [el for el in callout_elems if isinstance(el, Table)]
        if not tables:
            for el in callout_elems:
                if isinstance(el, KeepTogether):
                    tables.extend([f for f in el._content if isinstance(f, Table)])
        self.assertTrue(len(tables) >= 1)


if __name__ == "__main__":
    unittest.main()
