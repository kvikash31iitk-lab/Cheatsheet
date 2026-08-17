import unittest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from bot import author


class AuthorLimitTests(unittest.TestCase):
    def test_strip_reasoning_keeps_final_answer(self):
        self.assertEqual(
            author._strip_reasoning("<think>private work</think>\n# Final"),
            "# Final",
        )

    @patch("groq.Groq")
    def test_qwen_disables_reasoning_and_clamps_completion(self, groq_cls):
        response = MagicMock()
        response.choices[0].message.content = "# Clean output"
        response.usage = None
        create = groq_cls.return_value.chat.completions.create
        create.return_value = response

        with patch.object(author, "AUTHORING_MODEL", "qwen/qwen3.6-27b"):
            result = author._author_groq("system", "user", max_tokens=9000)

        self.assertEqual(result, "# Clean output")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["reasoning_effort"], "none")
        self.assertEqual(kwargs["reasoning_format"], "hidden")
        self.assertLessEqual(kwargs["max_tokens"], author.TPM_LIMIT_TOKENS)

    def test_groq_rejects_prompt_with_no_completion_room(self):
        oversized = "x" * (author.TPM_LIMIT_TOKENS * 3)
        with self.assertRaisesRegex(ValueError, "prompt is too large"):
            author._author_groq("system", oversized, max_tokens=1000)

    @patch("urllib.request.urlopen")
    def test_ollama_authoring_uses_local_chat_api(self, urlopen):
        payload = {
            "message": {"content": "<think>hidden</think>\n# Local output"},
            "prompt_eval_count": 12,
            "eval_count": 4,
        }
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        urlopen.return_value.__enter__.return_value = response
        usage = {}

        result = author._author_ollama(
            "system", "user", max_tokens=500, cost_sink=usage
        )

        self.assertEqual(result, "# Local output")
        self.assertEqual(usage, {"tokens_in": 12, "tokens_out": 4})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")

    @patch("subprocess.run")
    def test_codex_cli_captures_only_final_message(self, run_mock):
        def complete(cmd, **kwargs):
            output_path = Path(cmd[cmd.index("-o") + 1])
            output_path.write_text("<think>hidden</think>\n# Codex output", encoding="utf-8")
            return MagicMock(returncode=0, stdout="session log", stderr="")

        run_mock.side_effect = complete
        usage = {}
        with patch.object(author, "CODEX_CLI_BIN", "codex"):
            result = author._author_codex_cli(
                "system", "user", max_tokens=500, cost_sink=usage
            )

        self.assertEqual(result, "# Codex output")
        cmd = run_mock.call_args.args[0]
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--ignore-rules", cmd)
        self.assertIn("read-only", cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertNotIn("GROQ_API_KEY", run_mock.call_args.kwargs["env"])
        self.assertGreater(usage["tokens_in"], 0)
        self.assertGreater(usage["tokens_out"], 0)

    def test_codex_cli_auth_failure_falls_back_to_groq(self):
        usage = {}
        with (
            patch.object(author, "AUTHORING_PROVIDER", "codex_cli"),
            patch.object(author, "GROQ_API_KEY", "configured"),
            patch.object(
                author,
                "_author_codex_cli",
                side_effect=author.CodexCliUnrecoverableError("token expired"),
            ),
            patch.object(author, "_author_groq", return_value="# Groq fallback") as groq,
        ):
            result = author._author("system", "user", cost_sink=usage)

        self.assertEqual(result, "# Groq fallback")
        groq.assert_called_once()
        self.assertEqual(usage["fallback_used"], "groq")
        self.assertEqual(usage["fallback_reason"], "codex_cli_unrecoverable")

    def test_codex_expired_refresh_token_is_unrecoverable(self):
        self.assertTrue(
            author._should_fallback_from_claude(
                "",
                "Failed to refresh token: invalid_refresh_token; log out and sign in again",
            )
        )


if __name__ == "__main__":
    unittest.main()
