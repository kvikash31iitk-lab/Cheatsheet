from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.one_click_youtube import _choose_url, _ensure_authoring_ready


class OneClickUrlTests(unittest.TestCase):
    def test_explicit_url_is_selected_and_trailing_punctuation_removed(self):
        selected = _choose_url(
            "Please use https://youtu.be/dQw4w9WgXcQ?si=abc)."
        )
        self.assertEqual(selected, "https://youtu.be/dQw4w9WgXcQ?si=abc")

    @patch("scripts.one_click_youtube._clipboard_text")
    def test_clipboard_is_used_when_argument_is_absent(self, clipboard_mock):
        clipboard_mock.return_value = (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        self.assertEqual(
            _choose_url(None),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

    @patch("scripts.one_click_youtube._clipboard_text", return_value="not a link")
    @patch("scripts.one_click_youtube.sys.stdin.isatty", return_value=False)
    def test_missing_link_has_precise_error(self, _isatty_mock, _clipboard_mock):
        with self.assertRaisesRegex(ValueError, "No public YouTube link"):
            _choose_url(None)

    @patch("scripts.one_click_youtube._ollama_models")
    @patch("scripts.one_click_youtube.bot_config.AUTHORING_PROVIDER", "groq")
    def test_non_local_authoring_does_not_probe_ollama(self, models_mock):
        _ensure_authoring_ready()
        models_mock.assert_not_called()

    @patch("scripts.one_click_youtube.subprocess.run")
    @patch("scripts.one_click_youtube.shutil.which", return_value="ollama")
    @patch("scripts.one_click_youtube._ollama_models", return_value={"other:latest"})
    @patch("scripts.one_click_youtube.bot_config.AUTHORING_MODEL", "qwen2.5:7b")
    @patch("scripts.one_click_youtube.bot_config.AUTHORING_PROVIDER", "ollama")
    def test_missing_local_model_is_pulled_once(
        self, _models_mock, _which_mock, run_mock
    ):
        _ensure_authoring_ready()
        run_mock.assert_called_once_with(
            ["ollama", "pull", "qwen2.5:7b"], check=True
        )


if __name__ == "__main__":
    unittest.main()
