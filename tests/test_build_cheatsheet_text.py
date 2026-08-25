import unittest

from scripts.build_cheatsheet import _ascii_safe, _strip_summary_markers, inline


class CheatsheetTextRenderingTests(unittest.TestCase):
    def test_model_unicode_is_replaced_with_pdf_safe_ascii(self):
        text = "₹24,600 ≈ target → exit — don’t wait"

        self.assertEqual(
            _ascii_safe(text),
            "Rs. 24,600 ~ target -> exit - don't wait",
        )

    def test_inline_normalizes_before_escaping_markup(self):
        rendered = inline("Value ≤ 10 → **reduce**")

        self.assertIn("Value &lt;= 10 &rarr;", rendered)
        self.assertNotIn("→", rendered)

    def test_summary_markers_are_never_printed_as_document_text(self):
        markdown = "before\n<!--SUMMARY-->\nTL;DR content\n<!--/SUMMARY-->\nafter"
        cleaned = _strip_summary_markers(markdown)

        self.assertNotIn("<!--", cleaned)
        self.assertIn("TL;DR content", cleaned)


if __name__ == "__main__":
    unittest.main()
