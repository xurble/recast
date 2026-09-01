from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.middleware.security import SecurityMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from .views import editfeed, feed


class SubscriptionSettingsLinkTests(SimpleTestCase):
    def setUp(self):
        self.key = "subscription-key"
        self.canonical_path = reverse("editfeed", args=[self.key])

    def test_canonical_settings_url_resolves(self):
        match = resolve(self.canonical_path)

        self.assertIs(match.func, editfeed)
        self.assertEqual(match.kwargs, {"key": self.key})

    def test_legacy_settings_url_resolves(self):
        match = resolve(f"/feed/{self.key}/edit/")

        self.assertIs(match.func, editfeed)
        self.assertEqual(match.kwargs, {"key": self.key})

    def test_rss_emits_canonical_settings_url(self):
        edit_link = f"https://testserver{self.canonical_path}"
        post = {
            "title": "Test episode",
            "recast_link": "/post/1/",
            "author": None,
            "created": None,
            "created_for_subscription": "Sun, 30 Aug 2026 00:00:00 GMT",
            "body": "Episode description",
            "id": 1,
            "enclosures": SimpleNamespace(all=[]),
            "image_url": None,
        }

        rendered = render_to_string(
            "rss.xml",
            {
                "source": SimpleNamespace(
                    name="Test podcast",
                    image_url=None,
                ),
                "subscription": SimpleNamespace(
                    frequency=5,
                    key=self.key,
                ),
                "posts": [post],
                "edit_link": edit_link,
                "base_href": "https://testserver",
            },
        )

        self.assertIn(f"<link>{edit_link}</link>", rendered)
        self.assertEqual(rendered.count(edit_link), 2)
        self.assertNotIn(f"/feed/{self.key}/edit/", rendered)

    def test_administrator_page_emits_canonical_settings_url(self):
        subscription = SimpleNamespace(
            key=self.key,
            last_sent=4,
            complete=False,
            frequency=5,
            created=None,
            last_sent_date=None,
            last_accessed=None,
            user_agent=None,
            last_return_code=200,
        )
        source = SimpleNamespace(
            id=1,
            name="Test podcast",
            description=None,
            site_url="https://example.com",
            image_url=None,
            max_index=4,
            subscription_set=SimpleNamespace(all=lambda: [subscription]),
        )

        rendered = render_to_string(
            "source.html",
            {
                "source": source,
                "posts": [],
                "and_more": 0,
                "user": SimpleNamespace(is_superuser=True),
            },
        )

        self.assertIn(f'href="{self.canonical_path}"', rendered)
        self.assertNotIn(f"/feed/{self.key}/edit/", rendered)


class HttpsSecurityTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_security_defaults_follow_the_environment(self):
        production = not settings.DEBUG

        self.assertEqual(
            settings.MIDDLEWARE[0], "django.middleware.security.SecurityMiddleware"
        )
        self.assertEqual(settings.SECURE_SSL_REDIRECT, production)
        self.assertEqual(settings.SESSION_COOKIE_SECURE, production)
        self.assertEqual(settings.CSRF_COOKIE_SECURE, production)
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 31_536_000 if production else 0)
        self.assertFalse(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertFalse(settings.SECURE_HSTS_PRELOAD)

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_HSTS_SECONDS=31_536_000)
    def test_production_redirects_http_and_adds_hsts_to_https(self):
        middleware = SecurityMiddleware(lambda request: HttpResponse("ok"))

        redirect = middleware(self.factory.get("/help/"))
        secure_response = middleware(self.factory.get("/help/", secure=True))

        self.assertEqual(redirect.status_code, 301)
        self.assertEqual(redirect["Location"], "https://testserver/help/")
        self.assertEqual(
            secure_response["Strict-Transport-Security"], "max-age=31536000"
        )

    @override_settings(
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31_536_000,
    )
    def test_trusted_proxy_https_is_not_redirected(self):
        middleware = SecurityMiddleware(lambda request: HttpResponse("ok"))
        request = self.factory.get("/help/", HTTP_X_FORWARDED_PROTO="https")

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Strict-Transport-Security"], "max-age=31536000")

    @override_settings(
        SECURE_PROXY_SSL_HEADER=None,
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31_536_000,
    )
    def test_untrusted_forwarded_proto_does_not_bypass_redirect(self):
        middleware = SecurityMiddleware(lambda request: HttpResponse("ok"))
        request = self.factory.get("/help/", HTTP_X_FORWARDED_PROTO="https")

        response = middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://testserver/help/")

    @override_settings(
        DEBUG=True,
        SECURE_SSL_REDIRECT=False,
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_HSTS_SECONDS=0,
    )
    def test_development_allows_http_without_hsts(self):
        middleware = SecurityMiddleware(lambda request: HttpResponse("ok"))

        response = middleware(self.factory.get("/help/"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Strict-Transport-Security", response)

    @override_settings(
        SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
    )
    def test_production_session_and_csrf_cookies_are_secure(self):
        def view(request):
            request.session["authenticated"] = True
            get_token(request)
            return HttpResponse("ok")

        middleware = SessionMiddleware(CsrfViewMiddleware(view))

        response = middleware(self.factory.get("/", secure=True))

        self.assertTrue(response.cookies[settings.SESSION_COOKIE_NAME]["secure"])
        self.assertTrue(response.cookies[settings.CSRF_COOKIE_NAME]["secure"])


class FeedUserAgentTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.subscription = Mock(
            id=1,
            complete=True,
            last_sent=1,
            last_sent_date=timezone.now(),
        )
        self.subscription.source = Mock()

    def request_feed(self, **request_headers):
        request = self.factory.get(
            reverse("feed", args=["subscription-key"]),
            HTTP_HOST="testserver",
            **request_headers,
        )

        with (
            patch(
                "rc.views.Subscription.objects.get",
                return_value=self.subscription,
            ),
            patch("rc.views.Post.objects.filter") as posts,
            patch("rc.views.render", return_value=HttpResponse()) as render,
        ):
            posts.return_value.order_by.return_value = []
            response = feed(request, "subscription-key")

        self.assertEqual(response.status_code, 200)
        render.assert_called_once()

    def test_missing_user_agent_is_recorded_as_empty(self):
        self.request_feed()

        self.assertEqual(self.subscription.user_agent, "")

    def test_empty_user_agent_is_recorded_as_empty(self):
        self.request_feed(HTTP_USER_AGENT="")

        self.assertEqual(self.subscription.user_agent, "")

    def test_user_agent_is_recorded(self):
        self.request_feed(HTTP_USER_AGENT="PodcastClient/1.0")

        self.assertEqual(self.subscription.user_agent, "PodcastClient/1.0")

    def test_oversized_user_agent_is_truncated_to_model_limit(self):
        self.request_feed(HTTP_USER_AGENT="a" * 600)

        self.assertEqual(self.subscription.user_agent, "a" * 512)
        self.assertEqual(len(self.subscription.user_agent), 512)


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
