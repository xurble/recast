from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from .views import editfeed


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
