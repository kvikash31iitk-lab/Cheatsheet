from __future__ import annotations

import unittest

from scripts.ytdlp_client import is_valid_proxy_url


class ProxyUrlValidationTests(unittest.TestCase):
    def test_accepts_supported_schemes_with_explicit_host_and_port(self):
        accepted = (
            "http://proxy.example:80",
            "https://user:p%40ss@proxy.example:443",
            "socks5://127.0.0.1:1080",
            "socks5h://user:password@[2001:db8::1]:1080",
        )
        for value in accepted:
            with self.subTest(value=value.split(":", 1)[0]):
                self.assertTrue(is_valid_proxy_url(value))

    def test_rejects_ambiguous_or_unsupported_values(self):
        rejected = (
            "",
            "proxy.example:8000",
            "http://proxy.example",
            "ftp://proxy.example:21",
            "socks4://proxy.example:1080",
            "http://proxy.example:0",
            "http://proxy.example:65536",
            "http://proxy.example:8000/",
            "http://proxy.example:8000/path",
            "http://proxy.example:8000?session=x",
            "http://proxy.example:8000#fragment",
            "http://proxy.example:8000,https://other.example:9000",
            "http://proxy.example:8000\n",
            "http://user:raw space@proxy.example:8000",
        )
        for value in rejected:
            with self.subTest(value=value[:24]):
                self.assertFalse(is_valid_proxy_url(value))


if __name__ == "__main__":
    unittest.main()
