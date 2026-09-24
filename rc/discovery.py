"""Bounded synchronous public discovery and atomic initial persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from feeds.models import Enclosure, Post, Source

from .discovery_worker import DiscoveryError, http_url
from .models import DiscoveryQuota

DEFAULT_LIMITS = {
    "wire_bytes": 2 * 1024 * 1024,
    "body_bytes": 8 * 1024 * 1024,
    "entries": 500,
    "attachments_per_entry": 10,
    "attachments": 2000,
    "redirects": 3,
    "seconds": 15,
    "attempts_per_hour": 30,
    "sources": 10000,
}


def limits():
    configured = getattr(settings, "RECAST_DISCOVERY_LIMITS", {})
    if not isinstance(configured, dict) or configured.keys() - DEFAULT_LIMITS.keys():
        raise ImproperlyConfigured("Unknown RECAST_DISCOVERY_LIMITS setting")
    result = DEFAULT_LIMITS | configured
    if any(type(value) is not int or value <= 0 for value in result.values()):
        raise ImproperlyConfigured("RECAST_DISCOVERY_LIMITS values must be positive integers")
    return result


def existing_source(url):
    return Source.objects.filter(Q(feed_url__iexact=url) | Q(site_url__iexact=url)).first()


def locked_quota():
    # UPDATE is the first statement in the transaction. It takes a database write
    # lock on SQLite too, where select_for_update alone would be ineffective.
    if not DiscoveryQuota.objects.filter(pk=1).update(attempts=F("attempts") + 0):
        raise DiscoveryError("Feed discovery is unavailable until migrations are applied.", "unavailable", 503)
    return DiscoveryQuota.objects.get(pk=1)


def claim(limits):
    with transaction.atomic():
        quota = locked_quota()
        now = timezone.now()
        if quota.lease_until and quota.lease_until > now:
            raise DiscoveryError("Another feed is being checked. Please try again shortly.", "busy", 429)
        if quota.sources_created >= limits["sources"]:
            raise DiscoveryError("Public feed imports have reached capacity.", "capacity", 429)
        if not quota.window_started or now >= quota.window_started + timedelta(hours=1):
            quota.window_started = now
            quota.attempts = 0
        if quota.attempts >= limits["attempts_per_hour"]:
            raise DiscoveryError("Too many new feeds have been submitted. Please try again later.", "quota", 429)
        quota.attempts += 1
        quota.lease_token = uuid.uuid4().hex
        quota.lease_until = now + timedelta(seconds=limits["seconds"] + 30)
        quota.save()
        return quota.lease_token


def run_worker(url, limits):
    payload = {"url": url, "limits": limits,
               "agent": f"{settings.FEEDS_USER_AGENT} (+{settings.FEEDS_SERVER}; Initial Feed Crawler)"}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "rc.discovery_worker"],
            input=json.dumps(payload), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=limits["seconds"], check=True,
            # The worker needs no deployment environment, Django or credentials.
            env={"PATH": os.defpath}, cwd=Path(__file__).resolve().parent.parent,
        )
    except subprocess.TimeoutExpired as error:
        raise DiscoveryError("The feed took too long to read.", "timeout", 422) from error
    except (subprocess.CalledProcessError, OSError) as error:
        raise DiscoveryError("The feed could not be read.", "invalid", 422) from error
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise DiscoveryError("The feed could not be read.", "invalid", 422) from error
    if "error" in data:
        raise DiscoveryError(data["error"], data["reason"], data["status"])
    return data


def persist(url, data, token, limits):
    with transaction.atomic():
        quota = locked_quota()
        now = timezone.now()
        if quota.lease_token != token or quota.lease_until <= now:
            raise DiscoveryError("The feed import expired. Please try again.", "timeout")
        source = existing_source(url)
        if source:
            return source
        if quota.sources_created >= limits["sources"]:
            raise DiscoveryError("Public feed imports have reached capacity.", "capacity", 429)
        source = Source.objects.create(
            **data["source"], feed_url=url, num_subs=0, status_code=200,
            last_polled=now, last_success=now, last_change=now,
            # Do not immediately refetch the same feed in the refresh cron.
            due_poll=now + timedelta(minutes=400), max_index=len(data["posts"]),
            last_result="OK (bounded initial import)",
        )
        posts = []
        for index, item in enumerate(data["posts"], 1):
            fields = {key: value for key, value in item.items() if key not in {"enclosures", "created"}}
            posts.append(Post(source=source, index=index, created=datetime.fromisoformat(item["created"]), **fields))
        Post.objects.bulk_create(posts, batch_size=100)
        # MySQL doesn't return generated IDs from bulk_create. Read only this
        # bounded new source's IDs rather than relying on backend behavior.
        ids = dict(source.posts.values_list("index", "pk"))
        attachments = [Enclosure(post_id=ids[index], **attachment)
                       for index, item in enumerate(data["posts"], 1)
                       for attachment in item["enclosures"]]
        Enclosure.objects.bulk_create(attachments, batch_size=100)
        if timezone.now() >= quota.lease_until:
            raise DiscoveryError("The feed import expired. Please try again.", "timeout")
        quota.sources_created += 1
        quota.save(update_fields=["sources_created"])
        return source


def discover(url):
    url = http_url(url)
    source = existing_source(url)
    if source:
        return source, None
    policy = limits()
    token = claim(policy)
    try:
        data = run_worker(url, policy)
        if data["kind"] == "links":
            return None, data["links"]
        return persist(url, data, token, policy), None
    finally:
        # A stale worker must not release a replacement worker's lease.
        DiscoveryQuota.objects.filter(pk=1, lease_token=token).update(lease_token="", lease_until=None)
