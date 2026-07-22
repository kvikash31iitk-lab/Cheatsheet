from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.cookie_files import (
    CookieFileTooLarge,
    CookieFileValidationError,
    atomic_write_private,
    validate_cookie_file,
)
from api.youtube_urls import validate_public_youtube_url


YOUTUBE_COOKIE_VALUE = "dummy-cookie-value-never-returned"
VALID_COOKIE_TEXT = (
    "# Netscape HTTP Cookie File\r\n"
    "# exported locally\r\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\t"
    f"{YOUTUBE_COOKIE_VALUE}\r\n"
    ".google.com\tTRUE\t/\tTRUE\t2147483647\tNID\tdummy-google-value\r\n"
)


class CookieValidationTests(unittest.TestCase):
    def test_valid_file_is_normalized_and_counted(self) -> None:
        summary = validate_cookie_file("\ufeff" + VALID_COOKIE_TEXT)

        self.assertNotIn("\r", summary.normalized_text)
        self.assertTrue(summary.normalized_text.startswith("# Netscape HTTP Cookie File\n"))
        self.assertTrue(summary.normalized_text.endswith("\n"))
        self.assertEqual(summary.cookie_count, 2)
        self.assertEqual(summary.youtube_cookie_count, 1)
        self.assertEqual(
            summary.size_bytes,
            len(summary.normalized_text.encode("utf-8")),
        )

    def test_subdomain_youtube_cookie_is_accepted(self) -> None:
        raw = (
            "# Netscape HTTP Cookie File\n"
            "www.youtube.com\tFALSE\t/\tTRUE\t0\tPREF\tdummy\n"
        )

        summary = validate_cookie_file(raw)

        self.assertEqual(summary.youtube_cookie_count, 1)

    def test_header_only_file_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            CookieFileValidationError, "does not contain any cookie rows"
        ):
            validate_cookie_file("# Netscape HTTP Cookie File\n")

    def test_non_youtube_cookie_file_is_rejected(self) -> None:
        raw = (
            "# Netscape HTTP Cookie File\n"
            ".notyoutube.com\tTRUE\t/\tTRUE\t0\tSID\tdummy\n"
        )

        with self.assertRaisesRegex(
            CookieFileValidationError, "at least one youtube.com cookie"
        ):
            validate_cookie_file(raw)

    def test_malformed_row_error_never_contains_cookie_value(self) -> None:
        raw = (
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t"
            f"{YOUTUBE_COOKIE_VALUE}\textra-field\n"
        )

        with self.assertRaises(CookieFileValidationError) as raised:
            validate_cookie_file(raw)

        self.assertNotIn(YOUTUBE_COOKIE_VALUE, str(raised.exception))
        self.assertIn("line 2", str(raised.exception))

    def test_file_size_is_capped_by_utf8_bytes(self) -> None:
        with self.assertRaises(CookieFileTooLarge):
            validate_cookie_file("\u20ac" * 20, max_bytes=32)


class AtomicCookieWriteTests(unittest.TestCase):
    def test_private_atomic_write_replaces_file_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cookies.txt"
            target.write_text("old", encoding="utf-8")
            normalized = validate_cookie_file(VALID_COOKIE_TEXT).normalized_text

            atomic_write_private(target, normalized)

            self.assertEqual(target.read_text(encoding="utf-8"), normalized)
            self.assertEqual(list(target.parent.glob(".cookies.txt.*.tmp")), [])
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_failed_replace_preserves_existing_file_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cookies.txt"
            target.write_text("old", encoding="utf-8")

            with patch("api.cookie_files.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_private(target, "replacement\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(target.parent.glob(".cookies.txt.*.tmp")), [])


class YouTubeUrlValidationTests(unittest.TestCase):
    def test_supported_public_urls_are_accepted(self) -> None:
        urls = (
            "https://www.youtube.com/watch?v=N0mLsU4IxaA&t=10",
            "https://youtu.be/N0mLsU4IxaA?si=dummy",
            "https://www.youtube.com/shorts/N0mLsU4IxaA",
            "https://www.youtube-nocookie.com/embed/N0mLsU4IxaA",
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(validate_public_youtube_url(url), url)

    def test_whitespace_is_trimmed(self) -> None:
        url = "https://youtu.be/N0mLsU4IxaA"
        self.assertEqual(validate_public_youtube_url(f"  {url}\n"), url)

    def test_non_public_or_malformed_urls_are_rejected(self) -> None:
        urls = (
            "http://www.youtube.com/watch?v=N0mLsU4IxaA",
            "https://youtube.com.evil.example/watch?v=N0mLsU4IxaA",
            "https://youtube.com@evil.example/watch?v=N0mLsU4IxaA",
            "https://www.youtube.com:444/watch?v=N0mLsU4IxaA",
            "https://www.youtube.com/watch?v=too-short",
            "https://www.youtube.com/playlist?list=dummy",
        )

        for url in urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "valid public YouTube URL"):
                    validate_public_youtube_url(url)


if __name__ == "__main__":
    unittest.main()
