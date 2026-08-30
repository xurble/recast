from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from .views import editfeed


@override_settings(CLOUDFLARE_TOKEN="token", CLOUDFLARE_ZONE="zone")
class EditFeedCacheInvalidationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.key = "subscription-key"
        self.subscription = Mock()
        self.subscription.key = self.key
        self.subscription.frequency = 5
        self.subscription.last_sent = 4
        self.subscription.source.name = "Test podcast"
        self.subscription.source.description = None
        self.subscription.source.image_url = None
        self.subscription.source.max_index = 10
        self.subscription.source.posts.filter.return_value = []

    def post_edit(self, data):
        request = self.factory.post(
            reverse("editfeed", args=[self.key]), data, HTTP_HOST="testserver"
        )
        request.vals = {}

        with (
            patch("rc.views.get_object_or_404", return_value=self.subscription),
            patch("rc.views.render", return_value=HttpResponse()),
            patch("rc.views.CloudFlare.CloudFlare") as cloudflare,
        ):
            editfeed(request, self.key)

        return cloudflare.return_value

    def assert_feed_was_purged(self, cloudflare):
        cloudflare.zones.purge_cache.post.assert_called_once_with(
            "zone",
            data={"files": ["https://testserver/feed/subscription-key/"]},
        )

    def test_schedule_change_purges_personalized_feed(self):
        cloudflare = self.post_edit({"frequency": "3"})

        self.assertEqual(self.subscription.frequency, 3)
        self.subscription.save.assert_called_once_with()
        self.assert_feed_was_purged(cloudflare)

    def test_episode_position_change_purges_personalized_feed(self):
        cloudflare = self.post_edit({"release": "1", "episode": "4"})

        self.assertEqual(self.subscription.last_sent, 5)
        self.subscription.save.assert_called_once_with()
        self.assert_feed_was_purged(cloudflare)
