import datetime
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from feeds.models import Source

from .models import Subscription


@override_settings(CLOUDFLARE_TOKEN="test-token", CLOUDFLARE_ZONE="test-zone")
class SubscriptionStateTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.source = Source.objects.create(
            name="Podcast", feed_url="https://example.com/feed", max_index=10,
            due_poll=self.now,
        )
        self.sub = Subscription.objects.create(
            key="test-subscription", source=self.source, name="Podcast",
            last_sent=4, frequency=5, last_sent_date=self.now,
        )
        self.edit_url = reverse("editfeed", args=[self.sub.key])
        self.feed_url = reverse("feed", args=[self.sub.key])
        self.cf = self.enterContext(patch("rc.views.CloudFlare.CloudFlare"))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("Outbound HTTP")))

    def post(self, data):
        with patch("rc.views.timezone.now", return_value=self.now):
            response = self.client.post(self.edit_url, data, secure=True, HTTP_HOST="testserver")
        self.sub.refresh_from_db()
        return response

    def fetch(self):
        with patch("rc.views.timezone.now", return_value=self.now):
            response = self.client.get(self.feed_url, secure=True, HTTP_HOST="testserver")
        self.sub.refresh_from_db()
        return response

    def test_invalid_episode_and_frequency_do_not_mutate_or_purge(self):
        for field, invalid in (
            ("episode", ["-2000000000", "-1", "0", "11", "999999999999999999999", "wat", "1.5", "", None]),
            ("frequency", ["-1", "0", "15", "999999999999999999999", "wat", "1.5", "", None]),
        ):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    data = {"release": "1"} if field == "episode" else {}
                    if value is not None:
                        data[field] = value
                    self.assertEqual(self.post(data).status_code, 400)
                    self.assertEqual((self.sub.last_sent, self.sub.frequency, self.sub.last_sent_date), (4, 5, self.now))
                    self.cf.assert_not_called()

    def test_episode_boundaries_and_release_next(self):
        for value, expected in [(1, 1), (10, 10), (10, 10), (4, 4), (4, 5)]:
            with self.subTest(value=value, expected=expected):
                self.assertEqual(self.post({"release": "1", "episode": str(value)}).status_code, 200)
                self.assertEqual(self.sub.last_sent, expected)
                self.assertEqual(self.sub.last_sent_date, self.now)
        self.assertEqual(self.cf.return_value.zones.purge_cache.post.call_count, 5)

    def test_release_next_at_end_preserves_date(self):
        old_date = self.now - datetime.timedelta(days=1)
        self.sub.last_sent = 10
        self.sub.last_sent_date = old_date
        self.sub.save()
        self.assertEqual(self.post({"release": "1", "episode": "10"}).status_code, 200)
        self.assertEqual((self.sub.last_sent, self.sub.last_sent_date), (10, old_date))

    def test_frequency_boundaries_preserve_episode_schedule(self):
        for value in [1, 14]:
            with self.subTest(value=value):
                self.assertEqual(self.post({"frequency": str(value)}).status_code, 200)
                self.assertEqual((self.sub.last_sent, self.sub.frequency, self.sub.last_sent_date), (4, value, self.now))

    def test_empty_source_rejects_episode_selection(self):
        self.source.max_index = 0
        self.source.save()
        for value in [0, 1]:
            self.assertEqual(self.post({"release": "1", "episode": str(value)}).status_code, 400)
        self.cf.assert_not_called()

    def test_catch_up_preserves_strict_boundary_and_schedule(self):
        for elapsed, expected in [
            (datetime.timedelta(days=-1), 0),
            (datetime.timedelta(0), 0),
            (datetime.timedelta(days=5), 0),
            (datetime.timedelta(days=5, microseconds=1), 1),
            (datetime.timedelta(days=15), 2),
            (datetime.timedelta(days=16), 3),
            (datetime.timedelta(days=100), 6),
        ]:
            with self.subTest(elapsed=elapsed):
                start = self.now - elapsed
                self.sub.last_sent = 4
                self.sub.last_sent_date = start
                self.sub.complete = False
                self.sub.save()
                self.assertEqual(self.fetch().status_code, 200)
                self.assertEqual(self.sub.last_sent, 4 + expected)
                self.assertEqual(self.sub.last_sent_date, start + datetime.timedelta(days=5 * expected))
                self.assertEqual(self.sub.complete, expected == 6)

    def test_legacy_invalid_state_is_bounded_before_scheduling(self):
        for index, frequency, expected_index, expected_frequency in [
            (-2000000000, 0, 2, 1), (-1, -2000000000, 2, 1),
            (0, 2000000000, 1, 14), (2000000000, 5, 10, 5),
        ]:
            with self.subTest(index=index, frequency=frequency):
                self.sub.last_sent = index
                self.sub.frequency = frequency
                self.sub.last_sent_date = self.now - datetime.timedelta(days=2)
                self.sub.complete = False
                self.sub.save()
                self.assertEqual(self.fetch().status_code, 200)
                self.assertEqual((self.sub.last_sent, self.sub.frequency), (expected_index, expected_frequency))

    def test_catch_up_large_distance_uses_bounded_work(self):
        self.source.max_index = 2000000000
        self.source.save()
        self.sub.last_sent = -2000000000
        self.sub.frequency = 1
        self.sub.last_sent_date = self.now - datetime.timedelta(days=100000)
        self.sub.save()
        # Bound executed Python lines instead of relying on wall-clock timing.
        import sys
        from . import views
        count = 0
        def trace(frame, event, arg):
            nonlocal count
            if frame.f_code is views.feed.__code__ and event == "line":
                count += 1
                if count > 200:
                    raise AssertionError("Feed catch-up is iterating over missed episodes")
            return trace
        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            self.assertEqual(self.fetch().status_code, 200)
        finally:
            sys.settrace(previous)
        self.assertEqual(self.sub.last_sent, 100000)
        self.assertEqual(self.sub.last_sent_date, self.now - datetime.timedelta(days=1))
