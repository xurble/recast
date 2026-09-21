import time

from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.models import Count
from django.db.utils import OperationalError
from feeds.models import Source

from rc.models import Subscription


class Command(BaseCommand):
    help = "Reconcile Source.num_subs with Recast subscription counts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help="Database to reconcile (defaults to 'default').",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report stale counts without changing them.",
        )

    def handle(self, *args, **options):
        database = options["database"]
        dry_run = options["dry_run"]

        connection = connections[database]
        sqlite_timeout = float(
            connection.settings_dict.get("OPTIONS", {}).get("timeout", 5)
        )
        retry_deadline = time.monotonic() + max(sqlite_timeout, 0)

        while True:
            try:
                stale_sources, source_count = self._reconcile(database, dry_run)
                break
            except OperationalError as error:
                is_sqlite_lock = connection.vendor == "sqlite" and (
                    "locked" in str(error).lower() or "busy" in str(error).lower()
                )
                remaining = retry_deadline - time.monotonic()
                if not is_sqlite_lock or remaining <= 0:
                    raise
                time.sleep(min(0.05, remaining))

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {len(stale_sources)} of {source_count} source counts."
            )
        )

    def _reconcile(self, database, dry_run):
        with transaction.atomic(using=database):
            source_queryset = Source.objects.using(database).only("pk", "num_subs")
            if not dry_run:
                source_queryset = source_queryset.select_for_update()
            sources = list(source_queryset)
            counts = {
                row["source_id"]: row["total"]
                for row in (
                    Subscription.objects.using(database)
                    .values("source_id")
                    .annotate(total=Count("id"))
                )
            }
            stale_sources = [
                source
                for source in sources
                if source.num_subs != counts.get(source.pk, 0)
            ]

            if not dry_run:
                for source in stale_sources:
                    Source.objects.using(database).filter(pk=source.pk).update(
                        num_subs=counts.get(source.pk, 0)
                    )

        return stale_sources, len(sources)
