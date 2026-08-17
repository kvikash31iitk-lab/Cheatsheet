import unittest
import json
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


if __name__ == "__main__":
    unittest.main()
