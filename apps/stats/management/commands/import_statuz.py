"""Import official min-max reference prices (skeleton).

    python manage.py import_statuz --file prices.csv [--dry-run] [--region "Namangan viloyati"]

Without --file the stat.uz source is used, which is not connected yet (raises a clear error).
Rows whose product cannot be matched are reported and skipped, never guessed."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Product, ProductAlias
from apps.catalog.textnorm import normalize_text
from apps.stats.importers import CsvSource, StatUzSource
from apps.stats.models import ReferencePrice


def build_product_index():
    """normalised name/alias -> product id (names win over aliases on a clash)."""
    index = {}
    for key, pk in ProductAlias.objects.values_list("search_key", "product_id"):
        index.setdefault(key, pk)
    for key, pk in Product.objects.filter(is_active=True).values_list("search_key", "pk"):
        index[key] = pk
    return index


class Command(BaseCommand):
    help = "Import reference (min-max) prices from stat.uz or a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="CSV: product,date,min_price,max_price[,region]")
        parser.add_argument("--region", default="", help="Used for rows without a region column value.")
        parser.add_argument("--dry-run", action="store_true", help="Parse and match, but write nothing.")

    def handle(self, *args, **options):
        source = CsvSource(options["file"]) if options["file"] else StatUzSource()
        try:
            rows = list(source.fetch())
        except NotImplementedError as exc:
            raise CommandError(str(exc))
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc))

        index = build_product_index()
        created = updated = 0
        unmatched = set()
        with transaction.atomic():
            for row in rows:
                product_id = index.get(normalize_text(row.product_name))
                if product_id is None:
                    unmatched.add(row.product_name)
                    continue
                if row.min_price > row.max_price:
                    raise CommandError(f"{row.product_name} {row.date}: min_price > max_price")
                if options["dry_run"]:
                    created += 1
                    continue
                _, was_created = ReferencePrice.objects.update_or_create(
                    product_id=product_id, region=row.region or options["region"], date=row.date,
                    source=source.name,
                    defaults={"min_price": row.min_price, "max_price": row.max_price})
                created += was_created
                updated += not was_created

        for name in sorted(unmatched):
            self.stderr.write(f"Unmatched product skipped: {name!r}")
        mode = "DRY RUN - would write" if options["dry_run"] else "Wrote"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: {created} new, {updated} updated, {len(unmatched)} unmatched product name(s)."))
