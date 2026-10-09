from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from io import StringIO
from threading import Event, local
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.db.models import QuerySet
from django.db.utils import OperationalError
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.middleware.security import SecurityMiddleware
from django.template.loader import render_to_string
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.urls import resolve, reverse
from django.utils import timezone
from feeds.models import Source

from .models import Subscription
from .views import editfeed, feed


class SubscriptionCountTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Test podcast",
            feed_url="https://example.com/feed.xml",
            num_subs=0,
        )

    def create_subscription(self, key):
        return Subscription.objects.create(
            source=self.source,
            key=key,
            name="Test podcast",
            last_sent_date=timezone.now(),
        )

    def test_creation_updates_source_subscription_count(self):
        self.create_subscription("first")
        self.create_subscription("second")

        self.source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 2)

    def test_creation_replaces_the_source_default_with_the_actual_count(self):
        source = Source.objects.create(
            name="Default-count podcast",
            feed_url="https://example.com/default-count.xml",
        )
        self.assertEqual(source.num_subs, 1)

        Subscription.objects.create(
            source=source,
            key="default-count",
            name="Default-count podcast",
            last_sent_date=timezone.now(),
        )

        source.refresh_from_db()
        self.assertEqual(source.num_subs, 1)

    def test_admin_deletion_updates_source_subscription_count(self):
        first = self.create_subscription("first")
        self.create_subscription("second")
        administrator = get_user_model().objects.create_superuser(
            username="administrator",
            email="admin@example.com",
            password="password",
        )
        self.client.force_login(administrator)

        response = self.client.post(
            reverse("admin:rc_subscription_delete", args=[first.pk]),
            {"post": "yes"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:rc_subscription_changelist"))
        self.assertFalse(Subscription.objects.filter(pk=first.pk).exists())
        self.source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 1)

    def test_bulk_deletion_updates_multiple_source_counts(self):
        first = self.create_subscription("first")
        second_source = Source.objects.create(
            name="Second podcast",
            feed_url="https://example.com/second.xml",
            num_subs=0,
        )
        second = Subscription.objects.create(
            source=second_source,
            key="second",
            name="Second podcast",
            last_sent_date=timezone.now(),
        )

        Subscription.objects.filter(pk__in=[first.pk, second.pk]).delete()

        self.source.refresh_from_db()
        second_source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 0)
        self.assertEqual(second_source.num_subs, 0)

    def test_deleting_stale_duplicate_instance_is_idempotent(self):
        first = self.create_subscription("first")
        self.create_subscription("second")
        stale_first = Subscription.objects.get(pk=first.pk)

        first.delete()
        stale_first.delete()

        self.source.refresh_from_db()
        self.assertEqual(Subscription.objects.filter(source=self.source).count(), 1)
        self.assertEqual(self.source.num_subs, 1)

    def test_reconcile_subscription_counts_repairs_stale_values(self):
        self.create_subscription("first")
        Source.objects.filter(pk=self.source.pk).update(num_subs=99)
        empty_source = Source.objects.create(
            name="Empty podcast",
            feed_url="https://example.com/empty.xml",
            num_subs=99,
        )

        output = StringIO()
        call_command("reconcile_subscription_counts", stdout=output)

        self.source.refresh_from_db()
        empty_source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 1)
        self.assertEqual(empty_source.num_subs, 0)
        self.assertIn("Updated 2 of 2 source counts.", output.getvalue())

    def test_reconcile_subscription_counts_dry_run_does_not_write(self):
        Source.objects.filter(pk=self.source.pk).update(num_subs=99)

        output = StringIO()
        call_command("reconcile_subscription_counts", "--dry-run", stdout=output)

        self.source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 99)
        self.assertIn("Would update 1 of 1 source counts.", output.getvalue())

    def test_reconcile_locks_each_source_in_a_separate_transaction(self):
        Source.objects.filter(pk=self.source.pk).update(num_subs=99)
        Source.objects.create(
            name="Second podcast",
            feed_url="https://example.com/second.xml",
            num_subs=99,
        )
        output = StringIO()

        with patch(
            "rc.management.commands.reconcile_subscription_counts.transaction.atomic",
            wraps=transaction.atomic,
        ) as atomic:
            call_command("reconcile_subscription_counts", stdout=output)

        self.assertEqual(atomic.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs == {"using": "default"}
                for call in atomic.call_args_list
            )
        )
        self.assertIn("Updated 2 of 2 source counts.", output.getvalue())

    def test_reconcile_retry_reports_the_cumulative_source_population(self):
        output = StringIO()
        attempts = 0

        def reconcile(
            command,
            database,
            dry_run,
            encountered_source_ids,
            updated_source_ids,
        ):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                encountered_source_ids.update({1, 2})
                updated_source_ids.add(1)
                raise OperationalError("database is locked")

            encountered_source_ids.add(2)
            updated_source_ids.add(2)
            return updated_source_ids, len(encountered_source_ids)

        with (
            patch(
                "rc.management.commands.reconcile_subscription_counts.Command._reconcile",
                new=reconcile,
            ),
            patch("rc.management.commands.reconcile_subscription_counts.time.sleep"),
        ):
            call_command("reconcile_subscription_counts", stdout=output)

        self.assertEqual(attempts, 2)
        self.assertIn("Updated 2 of 2 source counts.", output.getvalue())


class ConcurrentSubscriptionCountTests(TransactionTestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Concurrent podcast",
            feed_url="https://example.com/concurrent.xml",
            num_subs=0,
        )

    def test_competing_creations_do_not_overwrite_a_newer_count(self):
        first_update_started = Event()
        release_first_update = Event()
        worker_state = local()
        original_update = QuerySet.update

        def coordinate_source_updates(queryset, **kwargs):
            if queryset.model is Source and getattr(worker_state, "delay", False):
                first_update_started.set()
                release_first_update.wait(timeout=5)
            return original_update(queryset, **kwargs)

        def create_subscription(key, *, delay):
            close_old_connections()
            worker_state.delay = delay
            try:
                Subscription.objects.create(
                    source_id=self.source.pk,
                    key=key,
                    name="Concurrent podcast",
                    last_sent_date=timezone.now(),
                )
            finally:
                close_old_connections()

        with (
            patch.object(QuerySet, "update", new=coordinate_source_updates),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(create_subscription, "first", delay=True)
            self.assertTrue(first_update_started.wait(timeout=5))
            second = executor.submit(create_subscription, "second", delay=False)
            try:
                second.result(timeout=5)
            finally:
                release_first_update.set()
            first.result(timeout=5)

        self.source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 2)
        self.assertEqual(
            Subscription.objects.filter(source=self.source).count(),
            self.source.num_subs,
        )

    def test_reconciliation_cannot_double_count_a_creation(self):
        Source.objects.filter(pk=self.source.pk).update(num_subs=99)
        counter_update_started = Event()
        reconciliation_started = Event()
        release_counter_update = Event()
        output = StringIO()

        from . import models as rc_models

        original_recount = rc_models._recount_source_subscriptions

        def delay_counter_update(source_id, using):
            counter_update_started.set()
            release_counter_update.wait(timeout=5)
            return original_recount(source_id, using)

        def create_subscription():
            close_old_connections()
            try:
                Subscription.objects.create(
                    source_id=self.source.pk,
                    key="reconciled",
                    name="Concurrent podcast",
                    last_sent_date=timezone.now(),
                )
            finally:
                close_old_connections()

        def reconcile_counts():
            close_old_connections()
            reconciliation_started.set()
            try:
                call_command("reconcile_subscription_counts", stdout=output)
            finally:
                close_old_connections()

        with (
            patch(
                "rc.models._recount_source_subscriptions",
                new=delay_counter_update,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            creation = executor.submit(create_subscription)
            self.assertTrue(counter_update_started.wait(timeout=5))
            reconciliation = executor.submit(reconcile_counts)
            self.assertTrue(reconciliation_started.wait(timeout=5))
            try:
                reconciliation.result(timeout=0.25)
            except FutureTimeoutError:
                pass
            finally:
                release_counter_update.set()
            creation.result(timeout=5)
            reconciliation.result(timeout=5)

        self.source.refresh_from_db()
        self.assertEqual(self.source.num_subs, 1)
        self.assertIn("Updated 0 of 1 source counts.", output.getvalue())
        self.assertEqual(
            Subscription.objects.filter(source=self.source).count(),
            self.source.num_subs,
        )


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


@override_settings(DEBUG=False)
class FeedLookupFailureTests(TestCase):
    def setUp(self):
        self.url = reverse("feed", args=["missing-subscription-key"])

    def test_missing_subscription_is_cached_as_gone(self):
        response = self.client.get(self.url, secure=True)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response["Cache-Control"], "max-age=604800")
        self.assertIn("Expires", response)

    def test_lookup_failures_return_server_errors_without_cache_freshness(self):
        self.client.raise_request_exception = False
        for error in (OperationalError("database unavailable"), RuntimeError("lookup failed")):
            with self.subTest(error=type(error).__name__), patch(
                "rc.views.Subscription.objects.get", side_effect=error
            ):
                response = self.client.get(self.url, secure=True)

                self.assertEqual(response.status_code, 500)
                self.assertNotIn("Cache-Control", response)
                self.assertNotIn("Expires", response)
                self.assertNotContains(response, str(error), status_code=500)

    def test_lookup_failures_propagate_to_standard_error_handling(self):
        request = RequestFactory().get(self.url, secure=True)
        for error in (OperationalError("database unavailable"), RuntimeError("lookup failed")):
            with self.subTest(error=type(error).__name__), patch(
                "rc.views.Subscription.objects.get", side_effect=error
            ):
                with self.assertRaises(type(error)) as raised:
                    feed(request, "missing-subscription-key")
                self.assertIs(raised.exception, error)


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


class CompletionFeedTests(TestCase):
    def setUp(self):
        self.baseline = datetime(2026, 9, 1, 12, 30, tzinfo=datetime_timezone.utc)
        source = Source.objects.create(
            name="Completed podcast", feed_url="https://example.com/completed.xml",
            max_index=1, due_poll=self.baseline,
        )
        self.subscription = Subscription.objects.create(
            source=source, key="completed-podcast", name="Completed podcast",
            complete=True, last_sent=1, last_sent_date=self.baseline,
        )

    def request_at(self, elapsed, **headers):
        request = RequestFactory().get(
            reverse("feed", args=[self.subscription.key]),
            HTTP_HOST="testserver", **headers,
        )
        with patch("rc.views.timezone.now", return_value=self.baseline + elapsed):
            response = feed(request, self.subscription.key)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_return_code, response.status_code)
        return response

    def completion_items(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/rss+xml")
        root = ElementTree.fromstring(response.content)
        self.assertEqual(root.tag, "rss")
        return [item for item in root.findall("./channel/item")
                if item.findtext("title") == "Recast is complete"]

    def test_initial_rss_response_includes_etag(self):
        response = self.request_at(timedelta(days=1))

        self.assertEqual(self.completion_items(response), [])
        self.assertRegex(response["ETag"], rf'^"{self.subscription.pk}-[0-9a-f]{{64}}"$')

    def test_matching_etag_returns_not_modified(self):
        first = self.request_at(timedelta(days=1))
        response = self.request_at(
            timedelta(days=1), HTTP_IF_NONE_MATCH=first["ETag"],
        )

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["ETag"], first["ETag"])
        self.assertEqual(response["Cache-Control"], first["Cache-Control"])
        self.assertIn("Expires", response)

    def test_stale_etag_returns_current_rss_and_new_etag(self):
        first = self.request_at(timedelta(days=1))
        response = self.request_at(
            timedelta(days=3), HTTP_IF_NONE_MATCH=first["ETag"],
        )

        self.assertEqual(len(self.completion_items(response)), 1)
        self.assertNotEqual(response["ETag"], first["ETag"])
        self.assertNotEqual(response.content, first.content)

    def test_frequency_edit_invalidates_etag_when_rss_changes(self):
        first = self.request_at(timedelta(days=1))
        self.subscription.frequency = 6
        self.subscription.save()

        response = self.request_at(
            timedelta(days=1), HTTP_IF_NONE_MATCH=first["ETag"],
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"every 6 days", response.content)
        self.assertNotEqual(response.content, first.content)
        self.assertNotEqual(response["ETag"], first["ETag"])

    def test_two_days_and_just_before_three_have_no_completion_item(self):
        for elapsed in (timedelta(days=2), timedelta(days=3, microseconds=-1)):
            with self.subTest(elapsed=elapsed):
                self.assertEqual(self.completion_items(self.request_at(elapsed)), [])

    def test_completion_item_renders_throughout_days_three_to_six(self):
        for elapsed in [timedelta(days=day) for day in range(3, 7)] + [
            timedelta(days=7, microseconds=-1)
        ]:
            with self.subTest(elapsed=elapsed):
                items = self.completion_items(self.request_at(elapsed))
                self.assertEqual(len(items), 1)
                item = items[0]
                date = parsedate_to_datetime(item.findtext("pubDate"))
                self.assertEqual(date.replace(tzinfo=datetime_timezone.utc), self.baseline)
                self.assertEqual(item.findtext("guid"), "completed-podcast/fin!")
                self.assertEqual(item.find("enclosure").attrib, {
                    "url": "https://testserver/static/audio/end.mp3",
                    "length": "94875", "type": "audio/mpeg",
                })

    def test_seven_days_returns_gone_even_with_previous_etag(self):
        previous = self.request_at(timedelta(days=3))
        response = self.request_at(
            timedelta(days=7),
            HTTP_IF_NONE_MATCH=previous["ETag"],
        )
        self.assertEqual(response.status_code, 410)

    def test_completion_supports_conditional_requests(self):
        previous = self.request_at(timedelta(days=1))
        complete = self.request_at(
            timedelta(days=3), HTTP_IF_NONE_MATCH=previous["ETag"],
        )
        self.assertEqual(len(self.completion_items(complete)), 1)
        cached = self.request_at(
            timedelta(days=6), HTTP_IF_NONE_MATCH=complete["ETag"],
        )
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")
