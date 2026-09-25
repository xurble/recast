import socket
from unittest.mock import patch

from django.test import SimpleTestCase

from rc.public_http import UnsafeFeedURL, resolve_public_url


def answer(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, 443))


class PublicHTTPTests(SimpleTestCase):
    def setUp(self):
        self.dns = patch(
            "rc.public_http.socket.getaddrinfo",
            return_value=[answer("93.184.216.34")],
        ).start()
        self.addCleanup(patch.stopall)

    def test_rejects_unsafe_url_syntax_without_dns(self):
        urls = [
            "file:///etc/passwd", "ftp://example.com", "http://user:pw@example.com",
            "http://[fe80::1%25en0]/", "http://example.com\\@localhost/",
            " http://example.com", "http://example.com\n/", "http://example.com:99999",
            "http://example.com:0",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(UnsafeFeedURL):
                resolve_public_url(url)
        self.dns.assert_not_called()

    def test_rejects_nonpublic_and_transition_addresses(self):
        addresses = [
            "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
            "169.254.169.254", "100.100.100.200", "0.0.0.0", "192.0.2.1",
            "224.0.0.1", "240.0.0.1", "::1", "::", "fc00::1", "fe80::1",
            "ff02::1", "2001:db8::1", "::ffff:127.0.0.1", "2002:7f00:1::",
            "64:ff9b::7f00:1",
        ]
        for ip in addresses:
            self.dns.return_value = [answer(ip)]
            with self.subTest(ip=ip), self.assertRaises(UnsafeFeedURL):
                resolve_public_url("http://feed.example")

    def test_rejects_mixed_dns_answers_before_connection(self):
        self.dns.return_value = [answer("93.184.216.34"), answer("10.0.0.1")]
        with self.assertRaises(UnsafeFeedURL):
            resolve_public_url("http://feed.example")

    def test_dns_failure_is_safe(self):
        self.dns.side_effect = socket.gaierror("internal detail")
        with self.assertRaisesRegex(UnsafeFeedURL, "public HTTP"):
            resolve_public_url("https://feed.example")

    def test_normalizes_public_url_and_preserves_hostname(self):
        result = resolve_public_url("https://podcast.example:8443/feed?q=1#fragment")
        self.assertEqual(
            result,
            ("https://podcast.example:8443/feed?q=1", "podcast.example", 8443,
             "93.184.216.34", "podcast.example:8443"),
        )
