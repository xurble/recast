import socket
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, TestCase, RequestFactory
from feeds.models import Source

from rc.public_http import UnsafeFeedURL, public_get, resolve_public_url
from rc.views import addfeed


def answer(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, 443))


def response(body, url="https://podcast.example/feed", content_type="application/rss+xml"):
    result = requests.Response()
    result.status_code = 200
    result._content = body
    result.url = url
    result.headers["Content-Type"] = content_type
    return result


RSS = b'''<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>
<title>Public podcast</title><link>https://podcast.example/</link>
<item><guid>episode-one</guid><title>Episode one</title><description>Body</description>
<enclosure url="https://cdn.example/one.mp3" length="12" type="audio/mpeg"/>
</item></channel></rss>'''


class PublicHTTPTests(SimpleTestCase):
    def setUp(self):
        self.dns = patch("rc.public_http.socket.getaddrinfo", return_value=[answer("93.184.216.34")]).start()
        self.addCleanup(patch.stopall)

    def test_rejects_unsafe_url_syntax_without_dns(self):
        for url in ["file:///etc/passwd", "ftp://example.com", "http://user:pw@example.com",
                    "http://[fe80::1%25en0]/", "http://example.com\\@localhost/", " http://example.com",
                    "http://example.com\n/", "http://example.com:99999", "http://example.com:0"]:
            with self.subTest(url=url), self.assertRaises(UnsafeFeedURL):
                resolve_public_url(url)
        self.dns.assert_not_called()

    def test_rejects_nonpublic_and_transition_addresses(self):
        for ip in ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
                   "100.100.100.200", "0.0.0.0", "192.0.2.1", "224.0.0.1", "240.0.0.1",
                   "::1", "::", "fc00::1", "fe80::1", "ff02::1", "2001:db8::1",
                   "::ffff:127.0.0.1", "2002:7f00:1::", "64:ff9b::7f00:1"]:
            self.dns.return_value = [answer(ip)]
            with self.subTest(ip=ip), self.assertRaises(UnsafeFeedURL):
                resolve_public_url("http://feed.example")

    def test_rejects_mixed_dns_answers_before_connection(self):
        self.dns.return_value = [answer("93.184.216.34"), answer("10.0.0.1")]
        with patch("rc.public_http.urllib3.HTTPConnectionPool") as pool:
            with self.assertRaises(UnsafeFeedURL):
                public_get("http://feed.example")
            pool.assert_not_called()

    def test_dns_failure_is_safe(self):
        self.dns.side_effect = socket.gaierror("internal detail")
        with self.assertRaisesRegex(UnsafeFeedURL, "public HTTP"):
            resolve_public_url("https://feed.example")

    def test_pins_address_and_preserves_tls_hostname(self):
        self.dns.side_effect = [[answer("93.184.216.34")], [answer("127.0.0.1")]]
        with patch("rc.public_http.urllib3.HTTPSConnectionPool") as pool:
            raw = pool.return_value.__enter__.return_value.urlopen.return_value
            raw.status, raw.headers, raw.data = 200, {"Content-Type": "text/plain"}, b"ok"
            result = public_get("https://podcast.example:8443/feed?q=1")
            self.assertEqual(result.text, "ok")
            self.assertEqual(pool.call_args.args, ("93.184.216.34",))
            self.assertEqual(pool.call_args.kwargs["server_hostname"], "podcast.example")
            self.assertEqual(pool.call_args.kwargs["assert_hostname"], "podcast.example")
            self.assertEqual(pool.call_args.kwargs["cert_reqs"], "CERT_REQUIRED")
            call = pool.return_value.__enter__.return_value.urlopen.call_args
            self.assertEqual(call.args, ("GET", "/feed?q=1"))
            self.assertEqual(call.kwargs["headers"]["Host"], "podcast.example:8443")
            self.assertFalse(call.kwargs["redirect"])
            self.assertFalse(call.kwargs["retries"])
            self.assertEqual(self.dns.call_count, 1)

    def test_each_redirect_is_resolved_before_connection(self):
        self.dns.side_effect = [[answer("93.184.216.34")], [answer("169.254.169.254")]]
        with patch("rc.public_http.urllib3.HTTPConnectionPool") as pool:
            raw = pool.return_value.__enter__.return_value.urlopen.return_value
            raw.status, raw.headers, raw.data = 302, {"Location": "http://metadata.example/"}, b""
            with self.assertRaises(UnsafeFeedURL):
                public_get("http://public.example/")
            self.assertEqual(pool.call_count, 1)

    def test_public_relative_redirect_and_ipv6(self):
        self.dns.return_value = [answer("2606:4700:4700::1111")]
        with patch("rc.public_http.urllib3.HTTPConnectionPool") as pool:
            pool.return_value.__enter__.return_value.urlopen.side_effect = [
                Mock(status=302, headers={"Location": "/feed"}, data=b""),
                Mock(status=200, headers={}, data=b"ok")]
            result = public_get("http://public.example/start")
            self.assertEqual(result.url, "http://public.example/feed")
            self.assertEqual(pool.call_count, 2)
            self.assertEqual(self.dns.call_count, 2)

    def test_redirect_loop_is_bounded(self):
        with patch("rc.public_http.urllib3.HTTPConnectionPool") as pool:
            raw = pool.return_value.__enter__.return_value.urlopen.return_value
            raw.status, raw.headers, raw.data = 302, {"Location": "/again"}, b""
            with self.assertRaises(UnsafeFeedURL):
                public_get("http://public.example/")
            self.assertEqual(pool.call_count, 11)


class DiscoverySSRFTests(TestCase):
    def setUp(self):
        self.dns = patch("rc.public_http.socket.getaddrinfo", return_value=[answer("93.184.216.34")]).start()
        # Any accidental feed-reader fetch fails the test without network access.
        self.unrestricted = patch("requests.get", side_effect=AssertionError("Unrestricted fetch")).start()
        self.addCleanup(patch.stopall)

    def submit(self, url="https://podcast.example/feed"):
        request = RequestFactory().post("/addfeed/", {"feed": url, "ajax": "yep"}, HTTP_HOST="testserver")
        return addfeed(request)

    def test_direct_ssrf_never_connects_or_creates_source(self):
        self.dns.return_value = [answer("127.0.0.1")]
        with patch("rc.views.public_get") as fetch:
            result = self.submit("http://127.0.0.1/private")
            self.assertIn(b'"ok": false', result.content)
            self.assertNotIn(b"127.0.0.1", result.content)
            self.assertNotIn(b"private", result.content)
            fetch.assert_not_called()
        self.assertEqual(Source.objects.count(), 0)

    def test_imports_public_feed_without_unrestricted_refetch(self):
        with patch("rc.views.public_get", return_value=response(RSS)) as fetch:
            result = self.submit()
            self.assertIn(b'"ok": true', result.content)
            source = Source.objects.get()
            self.assertEqual(source.posts.count(), 1)
            self.assertEqual(source.posts.get().title, "Episode one")
            self.assertEqual(source.posts.get().enclosures.count(), 1)
            self.assertEqual(source.max_index, 1)
            fetch.assert_called_once()
            self.unrestricted.assert_not_called()

    def test_unsafe_pagination_rolls_back_entire_import(self):
        paged = RSS.replace(b"</channel>", b'<atom:link rel="next" href="http://internal.example/"/></channel>')
        self.dns.side_effect = [[answer("93.184.216.34")], [answer("10.0.0.1")]]
        with patch("rc.views.public_get", return_value=response(paged)):
            result = self.submit()
            self.assertIn(b'"ok": false', result.content)
        self.assertEqual(Source.objects.count(), 0)
        self.unrestricted.assert_not_called()

    def test_safe_pagination_uses_guarded_transport(self):
        paged = RSS.replace(b"</channel>", b'<atom:link rel="next" href="/page2"/></channel>')
        second = RSS.replace(b"episode-one", b"episode-two")
        with patch("rc.views.public_get", return_value=response(paged)):
            with patch("rc.feed_import.public_get", return_value=response(second, "https://podcast.example/page2")) as fetch:
                result = self.submit()
                self.assertIn(b'"ok": true', result.content)
                self.assertEqual(Source.objects.get().posts.count(), 2)
                self.assertEqual(fetch.call_args.args[0], "https://podcast.example/page2")
        self.unrestricted.assert_not_called()

    def test_json_import(self):
        body = b'{"title":"JSON podcast","home_page_url":"https://podcast.example/","items":[{"id":"one","title":"JSON episode","content_text":"body"}]}'
        with patch("rc.views.public_get", return_value=response(body, content_type="application/feed+json")):
            result = self.submit()
            self.assertIn(b'"ok": true', result.content)
            self.assertEqual(Source.objects.get().posts.get().title, "JSON episode")
        self.unrestricted.assert_not_called()

    def test_atom_import_preserves_namespaced_content(self):
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom podcast</title>
        <link href="https://podcast.example/"/><entry><id>one</id><title>Atom episode</title>
        <updated>2026-01-01T00:00:00Z</updated><content type="html">Episode body</content>
        <link rel="enclosure" href="https://cdn.example/one.mp3" type="audio/mpeg" length="12"/>
        </entry></feed>'''
        with patch("rc.views.public_get", return_value=response(atom, content_type="application/atom+xml")):
            result = self.submit()
            self.assertIn(b'"ok": true', result.content)
            post = Source.objects.get().posts.get()
            self.assertEqual(post.title, "Atom episode")
            self.assertIn("Episode body", post.body)
            self.assertEqual(post.enclosures.count(), 1)
        self.unrestricted.assert_not_called()

    def test_case_variant_pagination_cannot_bypass_guard(self):
        for link in [b'<atom:LINK rel="next" href="http://127.0.0.1/"/>',
                     b'<atom:link REL="next" href="http://169.254.169.254/"/>',
                     b'<atom:LiNk ReL="next" href="http://10.0.0.1/"/>']:
            with self.subTest(link=link):
                paged = RSS.replace(b"</channel>", link + b"</channel>")
                self.dns.side_effect = [[answer("93.184.216.34")], [answer("127.0.0.1")]]
                with patch("rc.views.public_get", return_value=response(paged)):
                    result = self.submit()
                self.assertIn(b'"ok": false', result.content)
                self.assertEqual(Source.objects.count(), 0)
                self.unrestricted.assert_not_called()

    def test_url_shaped_xml_response_is_data_not_a_resource(self):
        for body in [b"http://169.254.169.254/latest/meta-data/", b"http://127.0.0.1/",
                     b"file:///etc/passwd", b"/etc/passwd"]:
            with self.subTest(body=body):
                with patch("rc.views.public_get", return_value=response(body)):
                    with patch("feedparser.http.get", side_effect=AssertionError("Parser network")) as fetch:
                        with patch("feedparser.api.open", side_effect=AssertionError("Parser file"), create=True) as resource:
                            result = self.submit()
                            self.assertNotIn(b'"ok": true', result.content)
                            fetch.assert_not_called()
                            resource.assert_not_called()
        self.assertEqual(Source.objects.count(), 0)
        self.unrestricted.assert_not_called()

    def test_root_pagination_link_cannot_bypass_guard(self):
        for destination in ["http://127.0.0.1/private", "http://169.254.169.254/latest/meta-data/"]:
            with self.subTest(destination=destination):
                body = ('<link rel="next" href="' + destination + '">').encode() + RSS + b"</link>"
                self.dns.side_effect = [[answer("93.184.216.34")], [answer("127.0.0.1")]]
                with patch("rc.views.public_get", return_value=response(body)):
                    result = self.submit()
                self.assertIn(b'"ok": false', result.content)
                self.assertEqual(Source.objects.count(), 0)
                self.unrestricted.assert_not_called()
