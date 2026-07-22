from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.proxy_config import (
    MAX_PROXY_URL_BYTES,
    ProxyConfigurationError,
    ProxyFileManagementDisabled,
    ProxyManagedByEnvironment,
    _prepare_managed_proxy_parent,
    managed_proxy_status,
    remove_managed_proxy,
    save_managed_proxy,
    validate_proxy_url,
)


SECRET_PROXY = "socks5h://admin:do-not-return@proxy.example.com:1080"


class ProxyUrlValidationTests(unittest.TestCase):
    def test_supported_proxy_urls_are_accepted(self) -> None:
        values = (
            "http://proxy.example.com:8000",
            "https://user:password@proxy.example.com:443",
            "socks5://127.0.0.1:1080",
            "socks5h://[2001:db8::1]:1080",
        )

        for value in values:
            with self.subTest(value=value):
                self.assertEqual(validate_proxy_url(value), value)

    def test_unsafe_or_ambiguous_proxy_urls_are_rejected(self) -> None:
        values = (
            "ftp://proxy.example.com:21",
            "http://proxy.example.com",
            "http://:8000",
            "http://-bad.example:8000",
            "http://bad-.example:8000",
            "http://bad_host.example:8000",
            "http://example..com:8000",
            "http://.example.com:8000",
            "http://user:bad%zz@proxy.example.com:8000",
            "http://proxy.example.com:0",
            "http://proxy.example.com:65536",
            "http://proxy.example.com:not-a-port",
            "http://proxy.example.com:8000/path",
            "http://proxy.example.com:8000?query=yes",
            "http://proxy.example.com:8000#fragment",
            "http://first.example:1,http://second.example:2",
            " http://proxy.example.com:8000",
            "http://proxy.example.com:8000\n",
            "http://proxy.example.com:8000\x00suffix",
        )

        for value in values:
            with self.subTest(value=value[:24]):
                with self.assertRaises(ProxyConfigurationError) as raised:
                    validate_proxy_url(value)
                self.assertNotIn(value, str(raised.exception))

    def test_utf8_byte_size_is_capped_without_echoing_input(self) -> None:
        secret = "http://user:" + ("\u20ac" * MAX_PROXY_URL_BYTES) + "@proxy:8000"

        with self.assertRaises(ProxyConfigurationError) as raised:
            validate_proxy_url(secret)

        self.assertNotIn(secret, str(raised.exception))


class ManagedProxyFileTests(unittest.TestCase):
    @staticmethod
    def env(target: Path | str, **overrides: str) -> dict[str, str]:
        values = {
            "YTDLP_PROXY_FILE": str(target),
            "YTDLP_PROXY_POOL": "",
            "YTDLP_PROXY_URL": "",
        }
        values.update(overrides)
        return values

    def test_save_is_private_atomic_and_status_never_returns_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cheetsheet" / "managed-proxy"
            env = self.env(target)

            response = save_managed_proxy(SECRET_PROXY, env)

            self.assertEqual(
                response,
                {"proxy_configured": True, "proxy_source": "admin"},
            )
            self.assertEqual(set(response), {"proxy_configured", "proxy_source"})
            self.assertNotIn(SECRET_PROXY, repr(response))
            self.assertNotIn(str(target), repr(response))
            self.assertEqual(target.read_text(encoding="utf-8"), SECRET_PROXY)
            self.assertEqual(list(target.parent.glob(".managed-proxy.*.tmp")), [])
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)

    def test_only_dedicated_parent_is_chmodded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generic_target = root / "generic" / "proxy-secret"
            dedicated_target = root / "cheetsheet" / "proxy-secret"

            with patch("api.proxy_config.os.name", "posix"), patch(
                "api.proxy_config.os.chmod"
            ) as chmod_mock:
                _prepare_managed_proxy_parent(generic_target)
                chmod_mock.assert_not_called()

                _prepare_managed_proxy_parent(dedicated_target)
                chmod_mock.assert_called_once_with(dedicated_target.parent, 0o700)

    def test_environment_takes_precedence_without_reading_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "managed-proxy"
            target.write_text("invalid managed secret", encoding="utf-8")
            env = self.env(target, YTDLP_PROXY_URL="http://env.example:8000")

            response = managed_proxy_status(env)

            self.assertEqual(
                response,
                {"proxy_configured": True, "proxy_source": "environment"},
            )

    def test_invalid_or_insecure_managed_file_is_not_reported_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "managed-proxy"
            target.write_text("not a proxy", encoding="utf-8")
            if os.name != "nt":
                target.chmod(0o600)

            self.assertEqual(
                managed_proxy_status(self.env(target)),
                {"proxy_configured": False, "proxy_source": "none"},
            )

    def test_remove_is_idempotent_and_returns_only_safe_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "managed-proxy"
            env = self.env(target)
            save_managed_proxy(SECRET_PROXY, env)

            first = remove_managed_proxy(env)
            second = remove_managed_proxy(env)

            expected = {"proxy_configured": False, "proxy_source": "none"}
            self.assertEqual(first, expected)
            self.assertEqual(second, expected)
            self.assertFalse(target.exists())
            self.assertNotIn(SECRET_PROXY, repr(first))

    def test_environment_management_refuses_save_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "managed-proxy"
            target.write_text("keep-existing-file", encoding="utf-8")
            env = self.env(target, YTDLP_PROXY_POOL="http://env.example:8000")

            with self.assertRaises(ProxyManagedByEnvironment) as save_error:
                save_managed_proxy(SECRET_PROXY, env)
            with self.assertRaises(ProxyManagedByEnvironment):
                remove_managed_proxy(env)

            self.assertNotIn(SECRET_PROXY, str(save_error.exception))
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "keep-existing-file",
            )

    def test_explicit_blank_file_override_disables_admin_save(self) -> None:
        env = self.env("")

        with self.assertRaises(ProxyFileManagementDisabled) as raised:
            save_managed_proxy(SECRET_PROXY, env)

        self.assertNotIn(SECRET_PROXY, str(raised.exception))
        self.assertEqual(
            managed_proxy_status(env),
            {"proxy_configured": False, "proxy_source": "none"},
        )

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are unavailable")
    def test_group_readable_managed_file_is_not_reported_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "managed-proxy"
            target.write_text(SECRET_PROXY, encoding="utf-8")
            target.chmod(0o640)

            self.assertEqual(
                managed_proxy_status(self.env(target)),
                {"proxy_configured": False, "proxy_source": "none"},
            )


if __name__ == "__main__":
    unittest.main()
