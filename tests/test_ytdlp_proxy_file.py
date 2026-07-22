from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ytdlp_client


def completed(returncode: int, *, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["yt-dlp"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class ProxySecretFileTests(unittest.TestCase):
    def setUp(self) -> None:
        ytdlp_client._reset_runtime_state_for_tests()

    @staticmethod
    def env(proxy_file: Path | str, **overrides: str) -> dict[str, str]:
        values = {
            "YTDLP_PROXY_FILE": str(proxy_file),
            "YTDLP_REQUEST_INTERVAL_SECONDS": "0",
            "YTDLP_HTTP_SLEEP_SECONDS": "0",
            "YT_COOKIES_PATH": "",
        }
        values.update(overrides)
        return values

    def test_reads_one_proxy_url_from_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "proxy-url"
            secret.write_text(
                "socks5h://user:password@proxy.example:1080\n",
                encoding="utf-8",
            )
            if os.name != "nt":
                secret.chmod(0o600)

            self.assertEqual(
                ytdlp_client.configured_proxies(self.env(secret)),
                ("socks5h://user:password@proxy.example:1080",),
            )

    def test_env_pool_and_single_url_take_precedence_without_reading_file(self):
        missing = Path("this-file-must-not-be-read")
        pool_env = self.env(
            missing,
            YTDLP_PROXY_POOL="http://one:1,http://two:2",
            YTDLP_PROXY_URL="http://single:3",
        )
        single_env = self.env(missing, YTDLP_PROXY_URL="http://single:3")

        with patch("scripts.ytdlp_client.Path.open") as open_mock:
            self.assertEqual(
                ytdlp_client.configured_proxies(pool_env),
                ("http://one:1", "http://two:2"),
            )
            self.assertEqual(
                ytdlp_client.configured_proxies(single_env),
                ("http://single:3",),
            )

        open_mock.assert_not_called()

    def test_missing_file_or_explicitly_blank_path_means_no_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            self.assertEqual(ytdlp_client.configured_proxies(self.env(missing)), ())
        self.assertEqual(
            ytdlp_client.configured_proxies({"YTDLP_PROXY_FILE": ""}),
            (),
        )

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_file_is_read_fresh_for_each_logical_operation(self, run_mock):
        run_mock.return_value = completed(0)
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "proxy-url"
            if os.name != "nt":
                # chmod after each atomic-style rewrite below.
                mode = 0o600
            secret.write_text("http://first.example:8000\n", encoding="utf-8")
            if os.name != "nt":
                secret.chmod(mode)
            env = self.env(secret)

            ytdlp_client.run_ytdlp(["URL"], operation="probe", env=env)
            secret.write_text("http://second.example:9000\n", encoding="utf-8")
            if os.name != "nt":
                secret.chmod(mode)
            ytdlp_client.run_ytdlp(["URL"], operation="probe", env=env)

        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(
            [command[command.index("--proxy") + 1] for command in commands],
            ["http://first.example:8000", "http://second.example:9000"],
        )

    def test_present_but_invalid_file_fails_closed_without_secret_leakage(self):
        invalid_values = (
            "",
            "not-a-proxy-url",
            "http://first:1\nhttp://second:2\n",
            "http://user:do-not-leak@proxy.example:8000 trailing-space ",
        )
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "private-proxy-secret"
            for invalid in invalid_values:
                with self.subTest(invalid=invalid[:12]):
                    secret.write_text(invalid, encoding="utf-8")
                    if os.name != "nt":
                        secret.chmod(0o600)
                    with self.assertLogs("scripts.ytdlp_client", level="ERROR") as logs:
                        with self.assertRaises(ytdlp_client.YtDlpError) as raised:
                            ytdlp_client.configured_proxies(self.env(secret))

                    combined = "\n".join(logs.output)
                    self.assertEqual(
                        raised.exception.kind,
                        ytdlp_client.YtDlpFailureKind.CONFIGURATION,
                    )
                    self.assertNotIn(str(secret), str(raised.exception))
                    self.assertNotIn(str(secret), raised.exception.diagnostic)
                    self.assertNotIn(str(secret), combined)
                    self.assertNotIn("do-not-leak", str(raised.exception))
                    self.assertNotIn("do-not-leak", raised.exception.diagnostic)
                    self.assertNotIn("do-not-leak", combined)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are unavailable")
    def test_group_or_world_readable_secret_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "proxy-url"
            secret.write_text("http://proxy.example:8000\n", encoding="utf-8")
            secret.chmod(0o644)

            with self.assertRaises(ytdlp_client.YtDlpError) as raised:
                ytdlp_client.configured_proxies(self.env(secret))

        self.assertEqual(
            raised.exception.kind,
            ytdlp_client.YtDlpFailureKind.CONFIGURATION,
        )
        self.assertEqual(raised.exception.diagnostic, "proxy_file:insecure_permissions")


if __name__ == "__main__":
    unittest.main()
