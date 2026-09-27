from django.db import models, router, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

# Create your models here.

import time
import datetime
from datetime import timezone
from urllib.parse import urlencode
import logging
import sys
import email

from feeds.models import Source, Post


# A user subscription
class Subscription(models.Model):
    key = models.CharField(unique=True, max_length=64)
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    last_sent = models.IntegerField(default=1)
    last_sent_date = models.DateTimeField()
    frequency = models.IntegerField(
        default=5
    )  # in days.  A little faster than a week so most podcasts catch up
    name = models.CharField(max_length=255)
    complete = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True, null=True)
    last_accessed = models.DateTimeField(auto_now_add=True, null=True)
    last_return_code = models.IntegerField(default=0)
    user_agent = models.CharField(max_length=512, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)

        using = kwargs.get("using")
        if using is None and len(args) >= 3:
            using = args[2]
        using = using or router.db_for_write(type(self), instance=self)

        with transaction.atomic(using=using):
            # A no-op update takes a real write lock on SQLite as well as a row
            # lock on production databases, and keeps reconciliation from
            # observing the insert before its counter update.
            Source.objects.using(using).filter(pk=self.source_id).update(
                num_subs=models.F("num_subs")
            )
            return super().save(*args, **kwargs)

    def __str__(self):
        return "'%s' on id %s" % (self.name, self.key)

    def unreadCount(self):
        if self.source:
            return self.source.max_index - self.last_sent
        else:
            try:
                return self._unreadCount
            except:
                return -666

    @property
    def next_send_date(self):
        roll_date = self.last_sent_date + datetime.timedelta(days=self.frequency)
        return roll_date

    class Meta:
        ordering = ["-last_accessed"]


def _recount_source_subscriptions(source_id, using):
    with transaction.atomic(using=using):
        source = (
            Source.objects.using(using)
            .select_for_update()
            .filter(pk=source_id)
            .first()
        )
        if source is None:
            return

        count = Subscription.objects.using(using).filter(source_id=source_id).count()
        Source.objects.using(using).filter(pk=source_id).update(num_subs=count)


@receiver(
    post_save,
    sender=Subscription,
    dispatch_uid="rc.subscription.update_source_count_after_create",
)
def update_source_subscription_count_after_create(
    sender, instance, created, using, **kwargs
):
    if created:
        _recount_source_subscriptions(instance.source_id, using)


@receiver(
    post_delete,
    sender=Subscription,
    dispatch_uid="rc.subscription.update_source_count_after_delete",
)
def update_source_subscription_count_after_delete(sender, instance, using, **kwargs):
    _recount_source_subscriptions(instance.source_id, using)


class SubscriptionPost(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)


class DiscoveryQuota(models.Model):
    """One durable row bounds anonymous discovery across all web workers."""

    sources_created = models.PositiveIntegerField(default=0)
    lease_token = models.CharField(max_length=32, blank=True, default="")
    lease_until = models.DateTimeField(null=True)


class DiscoveryAttempt(models.Model):
    """A recent admission used to enforce the global rolling-hour budget."""

    quota = models.ForeignKey(
        DiscoveryQuota, on_delete=models.CASCADE, related_name="discovery_attempts"
    )
    created = models.DateTimeField(db_index=True)
