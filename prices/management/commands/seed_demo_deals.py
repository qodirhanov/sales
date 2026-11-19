"""OPTIONAL demo data for the marketplace home page. Never runs automatically.

    .venv\\Scripts\\python.exe manage.py seed_demo_deals

Idempotent: demo rows are tagged with source_url / a fixed user and skipped if present.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from prices.models import Location, PriceEntry, Product

DEMO_PROMO_URL = "https://uzum.uz/ru"


class Command(BaseCommand):
    help = "Create a few demo price rows (one promo + one cheaper-elsewhere pair). Idempotent."

    def handle(self, *args, **opts):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if user is None:
            user, created = User.objects.get_or_create(username="demo_seller")
            if created:
                user.set_unusable_password()
                user.save()

        locations = list(Location.objects.filter(is_active=True).select_related("district").order_by("id")[:2])
        products = list(Product.objects.filter(is_active=True).order_by("id")[:2])
        if len(locations) < 2 or len(products) < 2:
            raise CommandError("Need at least 2 active products and 2 active locations (run seed_data first).")
        shop, bazaar = locations
        promo_product, cheaper_product = products

        if shop.website == "":
            shop.website = "https://uzum.uz/ru"
            shop.save(update_fields=["website"])

        rows = []
        # Promo: price below old_price, with a direct product link.
        rows.append(dict(product=promo_product, location=shop, price=82000, old_price=100000,
                         quantity=1, unit=promo_product.base_unit, is_promo=True,
                         source_url=DEMO_PROMO_URL))
        # Cheaper elsewhere: bazaar is >10% below the shop (and a third baseline if available).
        unit = cheaper_product.base_unit
        rows.append(dict(product=cheaper_product, location=shop, price=20000, quantity=1, unit=unit))
        rows.append(dict(product=cheaper_product, location=bazaar, price=15000, quantity=1, unit=unit))

        created = 0
        for r in rows:
            exists = PriceEntry.objects.filter(
                product=r["product"], location=r["location"], price=r["price"], user=user,
                is_promo=r.get("is_promo", False),
            ).exists()
            if exists:
                continue
            PriceEntry.objects.create(user=user, created_at=timezone.now(), **r)
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Demo deals ready ({created} new rows)."))
