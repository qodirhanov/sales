"""Load the Namangan starter data. Safe to run repeatedly (update_or_create, never deletes)."""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import seed_data
from apps.catalog.models import Category, City, Place, Product, ProductAlias
from apps.catalog.textnorm import normalize_text


class Command(BaseCommand):
    help = "Seed Namangan: 1 city, categories, 25 products with aliases, 8 placeholder places."

    @transaction.atomic
    def handle(self, *args, **options):
        city, _ = City.objects.update_or_create(slug=seed_data.CITY["slug"], defaults={"name": seed_data.CITY["name"]})

        categories = {}
        for name, slug, order in seed_data.CATEGORIES:
            categories[slug], _ = Category.objects.update_or_create(
                slug=slug, defaults={"name": name, "sort_order": order})

        alias_count = 0
        for name, cat_slug, unit, pack, aliases in seed_data.PRODUCTS:
            product, _ = Product.objects.update_or_create(
                name=name,
                defaults={"category": categories[cat_slug], "default_unit": unit,
                          "pack_size": Decimal(pack) if pack else None, "is_active": True})
            for alias in aliases:
                if not ProductAlias.objects.filter(product=product, search_key=normalize_text(alias)).exists():
                    ProductAlias.objects.create(product=product, alias=alias)
                    alias_count += 1

        for name, kind, address, lat, lng, opens, closes in seed_data.PLACES:
            Place.objects.update_or_create(
                city=city, name=name,
                defaults={"type": kind, "address": address, "lat": Decimal(lat), "lng": Decimal(lng),
                          "opens_at": datetime.time.fromisoformat(opens),
                          "closes_at": datetime.time.fromisoformat(closes), "is_active": True})

        self.stdout.write(self.style.SUCCESS(
            f"Namangan: {Category.objects.count()} categories, {Product.objects.count()} products, "
            f"{ProductAlias.objects.count()} aliases (+{alias_count} new), {Place.objects.filter(city=city).count()} places. "
            "Places are placeholders - rename them in the admin."))

