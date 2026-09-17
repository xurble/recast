from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Count
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

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {len(stale_sources)} of {len(sources)} source counts."
            )
        )
