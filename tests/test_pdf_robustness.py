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


if __name__ == "__main__":
    unittest.main()
