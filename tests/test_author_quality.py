import unittest

from bot.author import _cheatsheet_quality_issues


class CheatsheetQualityTests(unittest.TestCase):
    def test_substantive_lightweight_cheatsheet_is_rejected(self):
        issues = _cheatsheet_quality_issues(
            "# Topic\n\n## 1. Summary\nA very short summary.",
            20 * 60,
        )

        self.assertTrue(any(issue.startswith("only ") for issue in issues))
        self.assertIn("no useful markdown table", issues)
        self.assertIn("fewer than three callouts", issues)

    def test_structured_cheatsheet_passes_quality_floor(self):
        body = " ".join(["specific"] * 810)
        markdown = f"""# Topic

## 1. Details
{body}

| Choice | Use when |
|---|---|
| A | Condition A |

> [!def] Term
> Definition

> [!example] Worked case
> Example

> [!warning] Avoid
> Warning
"""

        self.assertEqual(_cheatsheet_quality_issues(markdown, 20 * 60), [])

    def test_mid_length_draft_still_fails_density_check(self):
        body = " ".join(["specific"] * 700)
        markdown = f"""# Topic

{body}

| Choice | Use when |
|---|---|
| A | Condition A |

> [!def] Term
> Definition

> [!example] Worked case
> Example

> [!warning] Avoid
> Warning
"""

        issues = _cheatsheet_quality_issues(markdown, 20 * 60)
        self.assertTrue(any(issue.startswith("only ") for issue in issues))

    def test_short_video_does_not_require_long_form_structure(self):
        self.assertEqual(
            _cheatsheet_quality_issues("# Brief\nA short note.", 5 * 60), []
        )

    def test_ten_minute_lightweight_draft_is_repaired(self):
        body = " ".join(["specific"] * 470)
        markdown = f"""# Topic

{body}

| Claim | Status |
|---|---|
| A | Attributed |

> [!note] Context
> Note

> [!warning] Caveat
> Warning

> [!q] Check
> Answer
"""

        issues = _cheatsheet_quality_issues(markdown, 10 * 60)
        self.assertTrue(any(issue.startswith("only ") for issue in issues))


if __name__ == "__main__":
    unittest.main()
