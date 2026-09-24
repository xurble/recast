import gzip
import io
import json
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock, patch

from django.db import DatabaseError, close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from feeds.models import Enclosure, Post, Source

from . import discovery, discovery_worker as worker
from .models import DiscoveryQuota

URL = "https://podcast.example/feed"
RSS = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Podcast</title>
<link>https://podcast.example</link><description>Show description</description>
<item><guid>one</guid><title>Episode one</title><description>Episode body</description>
<pubDate>Sun, 30 Aug 2026 12:00:00 GMT</pubDate>
<enclosure url="https://podcast.example/one.mp3" length="42" type="audio/mpeg"/></item>
</channel></rss>'''
ATOM = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title>
<link rel="next" href="https://must-not-fetch.example/next"/>
<entry><id>atom-one</id><title>Atom entry</title><updated>2026-08-30T12:00:00Z</updated>
<content type="html">&lt;p&gt;Atom body&lt;/p&gt;</content>
<link rel="enclosure" href="https://podcast.example/atom.mp3" type="audio/mpeg"/></entry></feed>'''
JSON_FEED = json.dumps({"version": "https://jsonfeed.org/version/1.1", "title": "JSON podcast",
                       "home_page_url": "https://podcast.example", "items": [
                           {"id": "json-one", "title": "JSON entry", "content_html": "<p>JSON body</p>",
                            "author": {"name": "Author"}, "date_published": "2026-08-30T12:00:00Z",
                            "attachments": [{"url": "https://podcast.example/json.mp3", "mime_type": "audio/mpeg"}]}]}).encode()


def parsed():
    return worker.parse(RSS, "application/rss+xml", URL, discovery.DEFAULT_LIMITS)


class Raw(io.BytesIO):
    def read(self, size, decode_content=False):
        assert not decode_content
        return super().read(size)


def response(body=RSS, headers=None, status=200):
    result = Mock(status=status, headers=headers or {"Content-Type": "application/rss+xml"})
    result.raw = Raw(body)
    result.read = result.raw.read
    def close():
        result.raw.close()
    result.close = Mock(side_effect=close)
    return result


class FetchTests(SimpleTestCase):
    def fetch(self, reply, policy=None):
        resolved = (URL, "podcast.example", 443, "93.184.216.34", "podcast.example")
        with patch.object(worker, "resolve_public_url", return_value=resolved), \
                patch.object(worker.urllib3, "HTTPSConnectionPool") as factory:
            pool = factory.return_value.__enter__.return_value
            pool.urlopen.return_value = reply
            result = worker.fetch(URL, policy or discovery.DEFAULT_LIMITS, "test")
            pool.urlopen.assert_called_once()
            self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
            self.assertFalse(pool.urlopen.call_args.kwargs["preload_content"])
            self.assertFalse(pool.urlopen.call_args.kwargs["decode_content"])
            self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["Host"], "podcast.example")
            factory.assert_called_once_with(
                "93.184.216.34", port=443, cert_reqs="CERT_REQUIRED",
                ca_certs=worker.requests.certs.where(), assert_hostname="podcast.example",
                server_hostname="podcast.example",
            )
        self.assertTrue(reply.raw.closed)
        return result

    def test_identity_and_gzip(self):
        for body, encoding in [(RSS, "identity"), (gzip.compress(RSS), "gzip")]:
            with self.subTest(encoding=encoding):
                self.assertEqual(self.fetch(response(body, {"Content-Encoding": encoding}))[0], RSS)

    def test_oversized_declared_body_is_not_read(self):
        reply = response(headers={"Content-Length": "999999999"})
        reply.raw = Mock()
        with self.assertRaises(worker.DiscoveryError):
            self.fetch(reply)
        reply.raw.read.assert_not_called()

    def test_oversized_stream_with_no_length(self):
        with self.assertRaises(worker.DiscoveryError):
            self.fetch(response(b"x" * 100), discovery.DEFAULT_LIMITS | {"wire_bytes": 50})

    def test_compression_bomb_is_rejected(self):
        with self.assertRaises(worker.DiscoveryError):
            self.fetch(response(gzip.compress(b"x" * 100000), {"Content-Encoding": "gzip"}),
                       discovery.DEFAULT_LIMITS | {"body_bytes": 100})

    def test_unsupported_truncated_and_concatenated_compression(self):
        for body, encoding in [(b"anything", "br"), (gzip.compress(RSS)[:-5], "gzip"),
                               (gzip.compress(RSS) * 2, "gzip")]:
            with self.subTest(encoding=encoding, size=len(body)), self.assertRaises(worker.DiscoveryError):
                self.fetch(response(body, {"Content-Encoding": encoding}))

    def test_redirects_do_not_read_bodies_and_share_hop_limit(self):
        resolved = (URL, "podcast.example", 443, "93.184.216.34", "podcast.example")
        with patch.object(worker, "resolve_public_url", return_value=resolved) as resolve, \
                patch.object(worker.urllib3, "HTTPSConnectionPool") as factory:
            pool = factory.return_value.__enter__.return_value
            redirect = response(headers={"Location": "/next"}, status=302)
            redirect.raw = Mock()
            pool.urlopen.return_value = redirect
            with self.assertRaises(worker.DiscoveryError):
                worker.fetch(URL, discovery.DEFAULT_LIMITS, "test")
            self.assertEqual(pool.urlopen.call_count, 4)
            self.assertEqual(resolve.call_count, 4)
            redirect.raw.read.assert_not_called()

    def test_remote_error_does_not_read_body(self):
        reply = response(headers={"Server": "cloudflare"}, status=403)
        reply.raw = Mock()
        with self.assertRaises(worker.DiscoveryError) as error:
            self.fetch(reply)
        self.assertEqual(error.exception.reason, "cloudflare")
        reply.raw.read.assert_not_called()

    def test_private_destination_is_rejected_before_connection(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        with patch("rc.public_http.socket.getaddrinfo", return_value=private), \
                patch.object(worker.urllib3, "HTTPConnectionPool") as pool, \
                self.assertRaises(worker.DiscoveryError) as error:
            worker.fetch("http://private.example/feed", discovery.DEFAULT_LIMITS, "test")
        self.assertEqual(error.exception.reason, "invalid")
        pool.assert_not_called()

    def test_redirect_to_private_destination_is_rejected_before_connection(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        redirect = response(headers={"Location": "http://metadata.example/latest"}, status=302)
        with patch("rc.public_http.socket.getaddrinfo", side_effect=[public, private]), \
                patch.object(worker.urllib3, "HTTPConnectionPool") as pool, \
                self.assertRaises(worker.DiscoveryError):
            pool.return_value.__enter__.return_value.urlopen.return_value = redirect
            worker.fetch("http://public.example/feed", discovery.DEFAULT_LIMITS, "test")
        self.assertEqual(pool.call_count, 1)


class ParseTests(SimpleTestCase):
    def test_rss_atom_and_json_preserve_content_and_enclosures(self):
        for body, content_type in [(RSS, "application/rss+xml"), (ATOM, "application/atom+xml"), (JSON_FEED, "application/feed+json")]:
            with self.subTest(content_type=content_type), patch.object(worker.requests.Session, "get", side_effect=AssertionError("unexpected refetch")):
                result = worker.parse(body, content_type, URL, discovery.DEFAULT_LIMITS)
                self.assertEqual(result["kind"], "feed")
                self.assertEqual(len(result["posts"]), 1)
                self.assertTrue(result["posts"][0]["body"])
                self.assertEqual(len(result["posts"][0]["enclosures"]), 1)

    def test_xml_entry_limit_precedes_feedparser(self):
        body = b"<rss><channel>" + b"<item><title>x</title></item>" * 3 + b"</channel></rss>"
        with patch.object(worker.feedparser, "parse") as parse, self.assertRaises(worker.DiscoveryError):
            worker.parse(body, "application/rss+xml", URL, discovery.DEFAULT_LIMITS | {"entries": 2})
        parse.assert_not_called()

    def test_json_entry_limit(self):
        data = json.loads(JSON_FEED)
        data["items"] *= 3
        with self.assertRaises(worker.DiscoveryError):
            worker.parse(json.dumps(data).encode(), "application/json", URL, discovery.DEFAULT_LIMITS | {"entries": 2})

    def test_entities_are_rejected_before_expansion(self):
        body = b'<!DOCTYPE rss [<!ENTITY x "expanded">]><rss><channel><item>&x;</item></channel></rss>'
        with patch.object(worker.feedparser, "parse") as parse, self.assertRaises(worker.DiscoveryError):
            worker.parse(body, "application/rss+xml", URL, discovery.DEFAULT_LIMITS)
        parse.assert_not_called()

    def test_attachment_limits(self):
        data = json.loads(JSON_FEED)
        data["items"][0]["attachments"] *= 3
        for policy in [{"attachments": 2}, {"attachments_per_entry": 2}]:
            with self.subTest(policy=policy), self.assertRaises(worker.DiscoveryError):
                worker.parse(json.dumps(data).encode(), "application/json", URL, discovery.DEFAULT_LIMITS | policy)

    def test_html_discovery_resolves_links_without_fetching(self):
        result = worker.parse(b'<html><link rel="alternate" type="application/rss+xml" href="/rss" title="Show"></html>',
                              "text/html", URL, discovery.DEFAULT_LIMITS)
        self.assertEqual(result, {"kind": "links", "links": [{"url": "https://podcast.example/rss", "title": "Show"}]})

    def test_script_is_removed_from_json_body(self):
        data = json.loads(JSON_FEED)
        data["items"][0]["content_html"] = '<script>alert(1)</script><p>safe</p>'
        result = worker.parse(json.dumps(data).encode(), "application/json", URL, discovery.DEFAULT_LIMITS)
        self.assertNotIn("<script", result["posts"][0]["body"])

    def test_empty_feed_is_rejected(self):
        with self.assertRaises(worker.DiscoveryError):
            worker.parse(b"<rss><channel/></rss>", "application/rss+xml", URL, discovery.DEFAULT_LIMITS)


class DeadlineTests(SimpleTestCase):
    def test_real_stalled_child_is_killed_and_reaped(self):
        # Exercise actual subprocess timeout/cleanup, without an external server.
        real_popen = subprocess.Popen
        children = []
        def stalled(*args, **kwargs):
            process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(process)
            return process
        started = time.monotonic()
        with patch.object(discovery.subprocess, "Popen", side_effect=stalled):
            with self.assertRaises(worker.DiscoveryError) as error:
                discovery.run_worker(URL, discovery.DEFAULT_LIMITS | {"seconds": 0.1})
        self.assertEqual(error.exception.reason, "timeout")
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNotNone(children[0].poll())

    def test_worker_rejects_bad_url_in_real_subprocess(self):
        with self.assertRaises(worker.DiscoveryError):
            discovery.run_worker("file:///etc/passwd", discovery.DEFAULT_LIMITS)


class DiscoveryTests(TestCase):
    def setUp(self):
        DiscoveryQuota.objects.update_or_create(pk=1, defaults={"attempts": 0, "sources_created": 0,
                                                               "lease_until": None, "lease_token": "", "window_started": None})
        self.worker = patch.object(discovery, "run_worker", return_value=parsed()).start()
        self.addCleanup(patch.stopall)

    def submit(self, url=URL):
        return self.client.post("/addfeed/", {"feed": url, "ajax": "yep"}, secure=True)

    def test_success_imports_once_with_indices_and_body(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        source = Source.objects.get()
        self.assertEqual(source.max_index, 1)
        post = source.posts.get()
        self.assertEqual(post.index, 1)
        self.assertEqual(post.body, "Episode body")
        self.assertEqual(post.enclosures.get().length, 42)
        self.assertGreater(source.due_poll, timezone.now())
        quota = DiscoveryQuota.objects.get(pk=1)
        self.assertEqual((quota.attempts, quota.sources_created, quota.lease_token), (1, 1, ""))
        self.assertEqual(self.submit().json(), response.json())
        self.worker.assert_called_once()

    def test_invalid_compressed_slow_and_entry_heavy_results_do_not_persist(self):
        for reason in ["limit", "timeout", "invalid"]:
            with self.subTest(reason=reason):
                self.worker.side_effect = worker.DiscoveryError("Rejected feed", reason)
                self.assertEqual(self.submit().status_code, 422)
                self.assertFalse(Source.objects.exists())
                self.assertFalse(Post.objects.exists())
                self.assertFalse(Enclosure.objects.exists())
                self.assertEqual(DiscoveryQuota.objects.get(pk=1).lease_token, "")
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).attempts, 3)

    def test_database_failure_rolls_back_source_posts_and_lifetime_count(self):
        with patch.object(Enclosure.objects, "bulk_create", side_effect=DatabaseError("failed")):
            self.assertEqual(self.submit().status_code, 503)
        self.assertFalse(Source.objects.exists())
        self.assertFalse(Post.objects.exists())
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).sources_created, 0)
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).attempts, 1)

    @override_settings(RECAST_DISCOVERY_LIMITS={"attempts_per_hour": 1})
    def test_repeated_unique_sources_are_rejected_before_remote_work(self):
        self.submit()
        response = self.submit("https://different.example/rss")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["reason"], "quota")
        self.worker.assert_called_once()

    @override_settings(RECAST_DISCOVERY_LIMITS={"sources": 1})
    def test_lifetime_capacity_survives_source_deletion(self):
        self.submit()
        Source.objects.all().delete()
        response = self.submit("https://different.example/rss")
        self.assertEqual(response.json()["reason"], "capacity")
        self.worker.assert_called_once()

    def test_busy_slot_rejects_before_remote_work(self):
        discovery.claim(discovery.DEFAULT_LIMITS)
        self.assertEqual(self.submit().json()["reason"], "busy")
        self.worker.assert_not_called()

    def test_expired_window_and_crashed_slot_recover(self):
        DiscoveryQuota.objects.filter(pk=1).update(window_started=timezone.now() - timedelta(hours=2), attempts=30,
                                                  lease_token="dead", lease_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(self.submit().json()["ok"])
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).attempts, 1)

    def test_stale_worker_cannot_persist_or_release_replacement_lease(self):
        def replace(*args):
            DiscoveryQuota.objects.filter(pk=1).update(lease_token="replacement")
            return parsed()
        self.worker.side_effect = replace
        self.assertEqual(self.submit().status_code, 422)
        self.assertFalse(Source.objects.exists())
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).lease_token, "replacement")

    def test_html_choices_are_escaped_and_count_against_quota(self):
        self.worker.return_value = {"kind": "links", "links": [{"url": URL, "title": '<script>bad</script>'}]}
        response = self.submit()
        self.assertContains(response, "&lt;script&gt;")
        self.assertFalse(Source.objects.exists())
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).attempts, 1)

    def test_invalid_url_is_cleanly_rejected_before_admission(self):
        for url in ["https://[broken/feed", "https://podcast.example:99999/feed", "ftp://podcast.example/feed"]:
            with self.subTest(url=url):
                self.assertEqual(self.submit(url).status_code, 422)
        self.worker.assert_not_called()
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).attempts, 0)

    def test_missing_quota_fails_closed(self):
        DiscoveryQuota.objects.all().delete()
        self.assertEqual(self.submit().status_code, 503)
        self.worker.assert_not_called()


class ConcurrentQuotaTests(TransactionTestCase):
    def test_competing_workers_cannot_both_claim(self):
        DiscoveryQuota.objects.update_or_create(pk=1)
        barrier = threading.Barrier(2)
        def contender():
            close_old_connections()
            try:
                barrier.wait(timeout=3)
                return discovery.claim(discovery.DEFAULT_LIMITS)
            except (worker.DiscoveryError, DatabaseError):
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: contender(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(DiscoveryQuota.objects.get(pk=1).attempts, 1)
