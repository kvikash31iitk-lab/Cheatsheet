from __future__ import annotations

import unittest

from scripts.ytdlp_client import is_valid_proxy_url


class ProxyHostnameValidationTests(unittest.TestCase):
    def test_accepts_dns_idna_ipv4_and_ipv6_hosts(self):
        accepted = (
            "http://localhost:8000",
            "http://proxy-1.example.com:8000",
            "https://bücher.example:443",
            "socks5://192.0.2.10:1080",
            "socks5h://[2001:db8::10]:1080",
            "https://user:p%40ss@proxy.example:443",
        )
        for value in accepted:
            with self.subTest(value=value.rsplit(":", 1)[0]):
                self.assertTrue(is_valid_proxy_url(value))

    def test_rejects_malformed_dns_and_ip_hosts(self):
        overlong_label = "a" * 64
        overlong_hostname = ".".join(["a" * 63] * 5)
        rejected = (
            "http://-bad.example:8000",
            "http://bad-.example:8000",
            "http://bad_host.example:8000",
            "http://example..com:8000",
            "http://.example.com:8000",
            "http://example.com.:8000",
            f"http://{overlong_label}.example:8000",
            f"http://{overlong_hostname}:8000",
            "http://999.999.999.999:8000",
            "http://010.0.0.1:8000",
        )
        for value in rejected:
            with self.subTest(value=value[:32]):
                self.assertFalse(is_valid_proxy_url(value))

    def test_rejects_malformed_percent_escapes_anywhere(self):
        rejected = (
            "http://user:bad%@proxy.example:8000",
            "http://user:bad%2@proxy.example:8000",
            "http://user:bad%zz@proxy.example:8000",
            "http://bad%zz.example:8000",
        )
        for value in rejected:
            with self.subTest(value=value[:28]):
                self.assertFalse(is_valid_proxy_url(value))


if __name__ == "__main__":
    unittest.main()
