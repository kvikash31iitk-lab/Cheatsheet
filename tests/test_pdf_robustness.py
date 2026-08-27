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
                self.assertNotEqual(item.strip(), "")
                self.assertNotEqual(item.strip(), "**")
                self.assertFalse(item.startswith("- "))

    def test_inline_empty_handling(self):
        self.assertEqual(inline_book("**"), "")
        self.assertEqual(inline_book("   "), "")
        self.assertEqual(inline_cs("**"), "")

    def test_clean_latex_math_fractions_and_subscripts(self):
        from scripts.build_mcq_handbook import _clean_latex_math as math_mcq
        from scripts.build_cheatsheet import _clean_latex_math as math_cs
        from scripts.build_illustrated_book import _clean_latex_math as math_book

        sample_input = "Formula: Mass_{middle} ≈ frac{Mass_{1st} + Mass_{3rd}}{2}."
        expected_output = "Formula: Mass<sub>middle</sub> ~ (Mass<sub>1st</sub> + Mass<sub>3rd</sub>) / 2."

        for fn in (math_mcq, math_cs, math_book):
            self.assertEqual(fn(sample_input), expected_output)
            self.assertEqual(fn(r"\frac{a}{b}"), "a / b")
            self.assertEqual(fn(r"frac{1}{2}"), "1 / 2")
            self.assertEqual(fn(r"\dfrac{x + y}{z - w}"), "(x + y) / (z - w)")
            self.assertEqual(fn(r"\approx 10.5"), "~ 10.5")
            self.assertEqual(fn(r"\text{Mass}_{1st}"), "Mass<sub>1st</sub>")
            self.assertEqual(fn(r"\sqrt{x^2 + y^2}"), "√(x^2 + y^2)")

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
        from reportlab.platypus import Table

        callout_elems = make_callout("correct", "Option (C)", ["Direct explanation line."])
        tables = [el for el in callout_elems if isinstance(el, Table)]
        self.assertTrue(len(tables) >= 1)


if __name__ == "__main__":
    unittest.main()
