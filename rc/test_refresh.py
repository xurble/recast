import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from feeds.models import Source


class RefreshTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("Outbound HTTP")))
        self.enterContext(patch("rc.views.CloudFlare.CloudFlare"))

    def refresh(self):
        return self.client.get("/refresh/", secure=True)

    def test_named_dependency_arguments_and_response_output(self):
        def update(*, max_feeds, output):
            output.write("Refreshed feeds\n")

        with patch("rc.views.update_feeds", autospec=True, side_effect=update) as update_feeds:
            response = self.refresh()

        update_feeds.assert_called_once_with(max_feeds=3, output=response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response.content, b"Refreshed feeds\n")

    def test_real_dependency_processes_three_oldest_due_live_feeds(self):
        sources = []
        for minutes in (2, 4, 1, 3):
            sources.append(Source.objects.create(
                name=f"Due {minutes}", feed_url=f"https://example.com/{minutes}",
                due_poll=self.now - datetime.timedelta(minutes=minutes), live=True,
            ))
        Source.objects.create(name="Future", feed_url="https://example.com/future",
                              due_poll=self.now + datetime.timedelta(days=1), live=True)
        Source.objects.create(name="Inactive", feed_url="https://example.com/inactive",
                              due_poll=self.now - datetime.timedelta(days=1), live=False)

        def read(source, output):
            output.write(f"\nRead {source.name}")

        with patch("feeds.utils.read_feed", side_effect=read) as read_feed:
            response = self.refresh()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual([call.args[0].pk for call in read_feed.call_args_list],
                         [sources[1].pk, sources[3].pk, sources[0].pk])
        self.assertTrue(all(call.args[1] is response for call in read_feed.call_args_list))
        self.assertEqual(response.content, b"\nQueue size is 4\nProcessing 3\nRead Due 4\nRead Due 3\nRead Due 2")

    def test_empty_queue_returns_progress(self):
        with patch("feeds.utils.read_feed") as read_feed:
            response = self.refresh()
        read_feed.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\nQueue size is 0\nProcessing 0")
