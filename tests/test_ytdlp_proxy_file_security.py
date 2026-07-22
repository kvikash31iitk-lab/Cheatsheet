from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts import ytdlp_client


class ProxySecretFileSecurityTests(unittest.TestCase):
    @staticmethod
    def env(path: Path) -> dict[str, str]:
        return {"YTDLP_PROXY_FILE": str(path)}

    def test_oversized_file_fails_closed_with_fixed_code(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "private-proxy-url"
            secret.write_bytes(b"x" * (ytdlp_client.MAX_PROXY_FILE_BYTES + 1))
            if os.name != "nt":
                secret.chmod(0o600)

            with self.assertRaises(ytdlp_client.YtDlpError) as raised:
                ytdlp_client.configured_proxies(self.env(secret))

        self.assertEqual(
            raised.exception.kind,
            ytdlp_client.YtDlpFailureKind.CONFIGURATION,
        )
        self.assertEqual(raised.exception.diagnostic, "proxy_file:too_large")
        self.assertNotIn(str(secret), str(raised.exception))
        self.assertNotIn(str(secret), raised.exception.diagnostic)

    def test_symlink_fails_closed_with_fixed_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "actual-secret"
            link = root / "configured-secret"
            target.write_text("http://proxy.example:8000\n", encoding="utf-8")
            if os.name != "nt":
                target.chmod(0o600)
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks are unavailable to this test process")

            with self.assertRaises(ytdlp_client.YtDlpError) as raised:
                ytdlp_client.configured_proxies(self.env(link))

        self.assertEqual(
            raised.exception.kind,
            ytdlp_client.YtDlpFailureKind.CONFIGURATION,
        )
        self.assertEqual(raised.exception.diagnostic, "proxy_file:symlink")
        self.assertNotIn(str(link), str(raised.exception))
        self.assertNotIn(str(link), raised.exception.diagnostic)


if __name__ == "__main__":
    unittest.main()
