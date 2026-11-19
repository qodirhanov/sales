"""Copy the legacy `prices` data into apps.* (see apps/reports/legacy.py for the mapping).

    python manage.py import_legacy_prices --dry-run
    python manage.py import_legacy_prices --city namangan

Safe to repeat: it only adds what is missing and never touches legacy rows.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import City
from apps.reports.legacy import import_legacy


class Command(BaseCommand):
    help = "Copy legacy prices data (places, products, prices, confirmations, phones) into apps.*"

    def add_arguments(self, parser):
        parser.add_argument("--city", help="Put every legacy place into this city (slug), e.g. namangan. "
                                           "Default: one city per legacy region.")
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll back.")

    def handle(self, *args, **opts):
        if opts["city"] and not City.objects.filter(slug=opts["city"]).exists():
            raise CommandError(f"No city with slug '{opts['city']}'. Run seed_namangan first or omit --city.")
        stats = import_legacy(city_slug=opts["city"], dry_run=opts["dry_run"])
        self.stdout.write(("DRY RUN, nothing saved.\n" if opts["dry_run"] else "Done.\n"))
        for key in sorted(stats):
            self.stdout.write(f"  {key}: {stats[key]}")
        if not stats:
            self.stdout.write("  (no legacy data found)")
