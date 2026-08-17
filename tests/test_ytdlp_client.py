from __future__ import annotations

import subprocess
import sys
import tempfile
import types
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


class YtDlpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        ytdlp_client._reset_runtime_state_for_tests()

    @staticmethod
    def env(**overrides: str) -> dict[str, str]:
        values = {
            "YTDLP_REQUEST_INTERVAL_SECONDS": "0",
            "YTDLP_HTTP_SLEEP_SECONDS": "0",
            "YTDLP_NETWORK_RETRY_DELAYS_SECONDS": "",
            "YT_COOKIES_PATH": "",
        }
        values.update(overrides)
        return values

    def test_pool_is_trimmed_deduplicated_and_preferred_over_single(self):
        env = self.env(
            YTDLP_PROXY_POOL="  http://one:8000,\n socks5://two:9000, http://one:8000 ",
            YTDLP_PROXY_URL="http://ignored:7000",
        )

        self.assertEqual(
            ytdlp_client.configured_proxies(env),
            ("http://one:8000", "socks5://two:9000"),
        )

    def test_default_network_retries_cover_watchdog_restart_window(self):
        self.assertEqual(
            ytdlp_client._network_retry_delays({}),
            (12.0, 24.0, 48.0),
        )

    def test_invalid_network_retry_delay_values_fall_back_to_default(self):
        self.assertEqual(
            ytdlp_client._network_retry_delays(
                {"YTDLP_NETWORK_RETRY_DELAYS_SECONDS": "a,b"}
            ),
            (12.0, 24.0, 48.0),
        )

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_pool_start_rotates_once_per_logical_call(self, run_mock):
        run_mock.return_value = completed(0)
        env = self.env(YTDLP_PROXY_POOL="http://one:8000,http://two:8000")

        ytdlp_client.run_ytdlp(["--version"], operation="probe", env=env)
        ytdlp_client.run_ytdlp(["--version"], operation="probe", env=env)
        ytdlp_client.run_ytdlp(["--version"], operation="probe", env=env)

        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(
            [cmd[cmd.index("--proxy") + 1] for cmd in commands],
            ["http://one:8000", "http://two:8000", "http://one:8000"],
        )

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_rate_limit_fails_over_to_next_pool_route(self, run_mock):
        run_mock.side_effect = [
            completed(1, stderr="ERROR: HTTP Error 429: Too Many Requests"),
            completed(0, stdout="ok"),
        ]
        env = self.env(YTDLP_PROXY_POOL="http://one:8000,http://two:8000")

        result = ytdlp_client.run_ytdlp(
            ["--skip-download", "https://youtu.be/abcdefghijk"],
            operation="read video information",
            env=env,
        )

        self.assertEqual(result.stdout, "ok")
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(
            [cmd[cmd.index("--proxy") + 1] for cmd in commands],
            ["http://one:8000", "http://two:8000"],
        )
        self.assertTrue(all("--cookies" not in cmd for cmd in commands))

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_bot_challenge_fails_over_without_sending_cookies(self, run_mock):
        run_mock.side_effect = [
            completed(1, stderr="Sign in to confirm you're not a bot"),
            completed(0, stdout="ok"),
        ]
        env = self.env(
            YTDLP_PROXY_POOL="http://one:8000,http://two:8000",
            YT_COOKIES_PATH=__file__,
        )

        result = ytdlp_client.run_ytdlp(
            ["URL"], operation="read video information", env=env
        )

        self.assertEqual(result.stdout, "ok")
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertTrue(all("--cookies" not in command for command in commands))

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_network_failure_also_fails_over(self, run_mock):
        run_mock.side_effect = [
            completed(1, stderr="ERROR: ProxyError: connection refused"),
            completed(0),
        ]
        env = self.env(YTDLP_PROXY_POOL="socks5://one:1,socks5://two:2")

        ytdlp_client.run_ytdlp(["URL"], operation="download audio", env=env)

        self.assertEqual(run_mock.call_count, 2)

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_auth_failure_retries_same_route_with_cookies(self, run_mock):
        run_mock.side_effect = [
            completed(1, stderr="ERROR: This video is private. Login required"),
            completed(0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            cookies = Path(directory) / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            env = self.env(
                YTDLP_PROXY_POOL="http://one:8000,http://two:8000",
                YT_COOKIES_PATH=str(cookies),
            )

            ytdlp_client.run_ytdlp(["URL"], operation="download audio", env=env)

        first, second = [call.args[0] for call in run_mock.call_args_list]
        self.assertNotIn("--cookies", first)
        self.assertEqual(second[second.index("--cookies") + 1], str(cookies))
        self.assertEqual(
            first[first.index("--proxy") + 1],
            second[second.index("--proxy") + 1],
        )

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_members_only_failure_has_precise_safe_message(self, run_mock):
        run_mock.return_value = completed(
            1,
            stderr=(
                "ERROR: [youtube] BeP_edbTOqk: Join this channel to get access "
                "to members-only content like this video"
            ),
        )

        with self.assertRaises(ytdlp_client.YtDlpError) as raised:
            ytdlp_client.run_ytdlp(
                ["URL"], operation="read video information", env=self.env()
            )

        self.assertEqual(
            raised.exception.kind,
            ytdlp_client.YtDlpFailureKind.MEMBERS_ONLY,
        )
        self.assertIn("paid member", raised.exception.public_message)
        self.assertIn(
            "Refresh the cookies only if that account has access",
            raised.exception.public_message,
        )
        self.assertNotIn("BeP_edbTOqk", raised.exception.public_message)

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_members_only_failure_retries_same_route_with_cookies(self, run_mock):
        member_error = completed(
            1,
            stderr=(
                "ERROR: This is members-only content. "
                "Join this channel to get access"
            ),
        )
        run_mock.side_effect = [member_error, member_error]
        with tempfile.TemporaryDirectory() as directory:
            cookies = Path(directory) / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            env = self.env(
                YTDLP_PROXY_URL="http://one:8000",
                YT_COOKIES_PATH=str(cookies),
            )

            with self.assertRaises(ytdlp_client.YtDlpError) as raised:
                ytdlp_client.run_ytdlp(
                    ["URL"], operation="read video information", env=env
                )

        self.assertEqual(run_mock.call_count, 2)
        first, second = [call.args[0] for call in run_mock.call_args_list]
        self.assertNotIn("--cookies", first)
        self.assertEqual(second[second.index("--cookies") + 1], str(cookies))
        self.assertEqual(
            raised.exception.kind,
            ytdlp_client.YtDlpFailureKind.MEMBERS_ONLY,
        )

    def test_bot_challenge_takes_precedence_over_members_only_text(self):
        kind = ytdlp_client._classify_failure(
            "Sign in to confirm you're not a bot; members-only content"
        )

        self.assertEqual(kind, ytdlp_client.YtDlpFailureKind.RATE_LIMITED)
    def test_common_members_only_wording_is_classified(self):
        diagnostics = (
            "This is member-only content",
            "This video is available to this channel's members",
            "Your account needs the required membership level",
        )

        for diagnostic in diagnostics:
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(
                    ytdlp_client._classify_failure(diagnostic),
                    ytdlp_client.YtDlpFailureKind.MEMBERS_ONLY,
                )


    @patch("scripts.ytdlp_client.subprocess.run")
    def test_cookie_retry_rate_limit_can_fail_over_but_next_route_is_anonymous(
        self, run_mock
    ):
        run_mock.side_effect = [
            completed(1, stderr="ERROR: This video is private. Login required"),
            completed(1, stderr="HTTP Error 429: Too Many Requests"),
            completed(0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            cookies = Path(directory) / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            env = self.env(
                YTDLP_PROXY_POOL="http://one:8000,http://two:8000",
                YT_COOKIES_PATH=str(cookies),
            )

            ytdlp_client.run_ytdlp(["URL"], operation="download video", env=env)

        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertNotIn("--cookies", commands[0])
        self.assertIn("--cookies", commands[1])
        self.assertNotIn("--cookies", commands[2])
        self.assertEqual(commands[2][commands[2].index("--proxy") + 1], "http://two:8000")

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_rate_limit_never_retries_with_cookies(self, run_mock):
        run_mock.return_value = completed(
            1, stderr="ERROR: HTTP Error 429: Too Many Requests; use --cookies"
        )
        env = self.env(
            YTDLP_PROXY_URL="http://one:8000",
            YT_COOKIES_PATH=__file__,
        )

        with self.assertRaises(ytdlp_client.YtDlpError) as raised:
            ytdlp_client.run_ytdlp(["URL"], operation="download audio", env=env)

        self.assertEqual(raised.exception.kind, ytdlp_client.YtDlpFailureKind.RATE_LIMITED)
        self.assertEqual(run_mock.call_count, 1)
        self.assertNotIn("--cookies", run_mock.call_args.args[0])

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_final_route_bot_challenge_retries_with_cookies(self, run_mock):
        run_mock.side_effect = [
            completed(
                1,
                stderr=(
                    "WARNING: HTTP Error 429: Too Many Requests\n"
                    "ERROR: Sign in to confirm you're not a bot"
                ),
            ),
            completed(0, stdout="ok"),
        ]
        env = self.env(
            YTDLP_PROXY_URL="http://one:8000",
            YT_COOKIES_PATH=__file__,
        )

        result = ytdlp_client.run_ytdlp(
            ["URL"], operation="read video information", env=env
        )

        self.assertEqual(result.stdout, "ok")
        self.assertEqual(run_mock.call_count, 2)
        first, second = [call.args[0] for call in run_mock.call_args_list]
        self.assertNotIn("--cookies", first)
        self.assertEqual(second[second.index("--cookies") + 1], __file__)
        self.assertEqual(
            first[first.index("--proxy") + 1],
            second[second.index("--proxy") + 1],
        )

    @patch("scripts.ytdlp_client.time.sleep")
    @patch("scripts.ytdlp_client.subprocess.run")
    def test_single_network_route_recovers_after_reconnect(self, run_mock, sleep_mock):
        run_mock.side_effect = [
            completed(1, stderr="ERROR: ProxyError: connection refused"),
            completed(0, stdout="ok"),
        ]
        env = self.env(
            YTDLP_PROXY_URL="socks5://one:1",
            YTDLP_NETWORK_RETRY_DELAYS_SECONDS="12,24",
        )

        result = ytdlp_client.run_ytdlp(
            ["URL"], operation="read video information", env=env
        )

        self.assertEqual(result.stdout, "ok")
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(12.0)

    @patch("scripts.ytdlp_client.time.sleep")
    @patch("scripts.ytdlp_client.subprocess.run")
    def test_single_network_route_stops_after_bounded_retries(
        self, run_mock, sleep_mock
    ):
        run_mock.return_value = completed(
            1, stderr="ERROR: ProxyError: connection refused"
        )
        env = self.env(
            YTDLP_PROXY_URL="socks5://one:1",
            YTDLP_NETWORK_RETRY_DELAYS_SECONDS="1,2,3",
        )

        with self.assertRaises(ytdlp_client.YtDlpError) as raised:
            ytdlp_client.run_ytdlp(
                ["URL"], operation="read video information", env=env
            )

        self.assertEqual(raised.exception.kind, ytdlp_client.YtDlpFailureKind.NETWORK)
        self.assertEqual(run_mock.call_count, 4)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list], [1.0, 2.0, 3.0]
        )

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_public_error_and_logs_never_expose_proxy_credentials(self, run_mock):
        proxy = "http://alice:super-secret@proxy.example:8000"
        run_mock.return_value = completed(
            1,
            stderr=f"ProxyError while connecting via {proxy}: connection refused",
        )

        with self.assertLogs("scripts.ytdlp_client", level="INFO") as captured:
            with self.assertRaises(ytdlp_client.YtDlpError) as raised:
                ytdlp_client.run_ytdlp(
                    ["URL"],
                    operation="download video",
                    env=self.env(YTDLP_PROXY_URL=proxy),
                )

        self.assertNotIn("super-secret", str(raised.exception))
        self.assertNotIn("super-secret", raised.exception.diagnostic)
        self.assertNotIn("super-secret", "\n".join(captured.output))
        self.assertEqual(raised.exception.kind, ytdlp_client.YtDlpFailureKind.NETWORK)

    @patch("scripts.ytdlp_client.subprocess.run")
    def test_command_uses_current_defaults_without_forced_android_client(self, run_mock):
        run_mock.return_value = completed(0)

        ytdlp_client.run_ytdlp(
            ["--skip-download", "URL"],
            operation="probe",
            env={"YTDLP_REQUEST_INTERVAL_SECONDS": "0"},
        )

        command = run_mock.call_args.args[0]
        self.assertIn("--ignore-config", command)
        self.assertEqual(command[command.index("--js-runtimes") + 1], "node")
        self.assertIn("--sleep-requests", command)
        self.assertNotIn("--extractor-args", command)
        self.assertNotIn("--cookies", command)

    def test_client_profiles_are_bounded_deduplicated_and_configurable(self):
        profiles = ytdlp_client.youtube_client_profiles(
            self.env(YTDLP_CLIENT_PROFILES="android,default,android,unknown")
        )
        self.assertEqual([name for name, _args in profiles], ["android", "default"])

    @patch("scripts.ytdlp_client.run_ytdlp")
    def test_profile_fallback_advances_after_403(self, run_mock):
        blocked = ytdlp_client.YtDlpError(
            operation="download audio",
            kind=ytdlp_client.YtDlpFailureKind.RATE_LIMITED,
            public_message="blocked",
            diagnostic="HTTP Error 403",
            returncode=1,
        )
        run_mock.side_effect = [blocked, completed(0, stdout="ok")]
        seen = []

        result = ytdlp_client.run_ytdlp_profiles(
            ["URL"],
            operation="download audio",
            env=self.env(YTDLP_CLIENT_PROFILES="default,android"),
            on_profile=lambda name, *_: seen.append(name),
        )

        self.assertEqual(result.stdout, "ok")
        self.assertEqual(seen, ["default", "android"])
        second_args = run_mock.call_args_list[1].args[0]
        self.assertIn("youtube:player_client=android", second_args)

    @patch("scripts.ytdlp_client.run_ytdlp")
    def test_profile_fallback_stops_for_content_failure(self, run_mock):
        unavailable = ytdlp_client.YtDlpError(
            operation="metadata",
            kind=ytdlp_client.YtDlpFailureKind.UNAVAILABLE,
            public_message="gone",
            diagnostic="Video unavailable",
            returncode=1,
        )
        run_mock.side_effect = unavailable

        with self.assertRaises(ytdlp_client.YtDlpError):
            ytdlp_client.run_ytdlp_profiles(
                ["URL"],
                operation="metadata",
                env=self.env(YTDLP_CLIENT_PROFILES="default,android"),
            )

        self.assertEqual(run_mock.call_count, 1)


# transcribe_with_frames has an optional external Whisper helper at import time.
# A tiny stub keeps these focused downloader integration tests self-contained.
if "whisper" not in sys.modules:
    whisper_stub = types.ModuleType("whisper")
    whisper_stub._post_whisper = lambda *args, **kwargs: None
    whisper_stub.GROQ_ENDPOINT = ""
    whisper_stub.GROQ_MODEL = ""
    whisper_stub.load_api_key = lambda: ("groq", "test")
    sys.modules["whisper"] = whisper_stub

from scripts import transcribe_with_frames  # noqa: E402


class PipelineYtDlpIntegrationTests(unittest.TestCase):
    @patch("scripts.transcribe_with_frames.run_ytdlp")
    def test_metadata_uses_shared_runner(self, run_mock):
        run_mock.return_value = completed(
            0,
            stdout="abcdefghijk\nA title with | punctuation\n123.5\n",
        )

        result = transcribe_with_frames.fetch_metadata("https://youtu.be/abcdefghijk")

        self.assertEqual(
            result,
            {"id": "abcdefghijk", "title": "A title with | punctuation", "duration": 123.5},
        )
        self.assertEqual(run_mock.call_args.kwargs["operation"], "read video information")

    @patch("scripts.transcribe_with_frames.run_ytdlp_profiles")
    def test_video_download_uses_shared_runner(self, run_mock):
        run_mock.return_value = completed(0)
        with tempfile.TemporaryDirectory() as directory:
            output = transcribe_with_frames.ensure_video(
                "https://youtu.be/abcdefghijk", Path(directory)
            )

        self.assertEqual(output.name, "raw_video.mp4")
        self.assertEqual(run_mock.call_args.kwargs["operation"], "download video")


if __name__ == "__main__":
    unittest.main()
