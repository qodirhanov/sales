from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.catalog.models import Category, City, Place, Product

from .legacy import import_legacy
from .models import Confirmation, PriceReport

from prices import models as legacy

User = get_user_model()


class LegacyImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        legacy.Product.objects.all().delete()  # products seeded by legacy migration 0009 (PROTECT)
        legacy.Category.objects.all().delete()
        cls.user = User.objects.create_user("seller", password="pw")
        cls.voter = User.objects.create_user("voter", password="pw")
        top = legacy.Category.objects.create(name="Oziq-ovqat", slug="oziq")
        cat = legacy.Category.objects.create(name="Go'sht", slug="gosht", parent=top)
        cls.meat = legacy.Product.objects.create(name="Mol go'shti", category=cat, base_unit="kg")
        cls.oil = legacy.Product.objects.create(name="Paxta yog'i", category=cat, base_unit="l")
        region = legacy.Region.objects.create(name="Toshkent")
        d1 = legacy.District.objects.create(name="Chilonzor", region=region)
        d2 = legacy.District.objects.create(name="Yunusobod", region=region)
        # same name in two districts -> must not collide in the new (city, name) constraint
        cls.loc1 = legacy.Location.objects.create(name="Mega do'kon", type="shop", district=d1, address="1-uy",
                                                  website="https://mega.example")
        cls.loc2 = legacy.Location.objects.create(name="Mega do'kon", type="shop", district=d2)
        cls.when = timezone.now() - timedelta(days=2)

    def entry(self, **kw):
        defaults = dict(product=self.meat, location=self.loc1, user=self.user, price=95000, quantity=1,
                        unit="kg", created_at=self.when)
        defaults.update(kw)
        return legacy.PriceEntry.objects.create(**defaults)

    def test_copies_catalog_places_and_reports(self):
        self.entry()
        self.entry(product=self.oil, unit="ml", price=8000, quantity=500, location=self.loc2,
                   is_promo=True, old_price=10000, source_url="https://shop.example/oil")
        import_legacy()
        self.assertEqual(Category.objects.count(), 2)  # flattened: parent and child both kept
        self.assertEqual(Product.objects.get(name="Paxta yog'i").default_unit, "litr")
        names = sorted(Place.objects.values_list("name", flat=True))
        self.assertEqual(names, ["Mega do'kon (Chilonzor)", "Mega do'kon (Yunusobod)"])
        place = Place.objects.get(name="Mega do'kon (Chilonzor)")
        self.assertEqual(place.address, "Chilonzor, 1-uy")
        self.assertEqual(place.website, "https://mega.example")
        self.assertEqual(City.objects.get().name, "Toshkent")
        promo = PriceReport.objects.get(product__name="Paxta yog'i")
        self.assertEqual((promo.unit, promo.is_promo, promo.old_price), ("ml", True, 10000))
        self.assertEqual(promo.source_url, "https://shop.example/oil")
        self.assertEqual(promo.normalized_price, Decimal("16000.00"))  # 8 000 / 0.5 l
        self.assertEqual(promo.created_at, self.when)

    def test_status_follows_flag_and_confirmations_are_copied(self):
        ok = self.entry()
        bad = self.entry(price=400000)
        legacy.PriceEntry.objects.filter(pk=bad.pk).update(is_flagged=True)
        legacy.PriceConfirmation.objects.create(entry=ok, user=self.voter)
        import_legacy()
        self.assertEqual(PriceReport.objects.get(price=95000).status, "confirmed")
        self.assertEqual(PriceReport.objects.get(price=400000).status, "flagged")
        c = Confirmation.objects.get()
        self.assertEqual((c.user, c.weight), (self.voter, Decimal("1.00")))

    def test_is_repeatable(self):
        self.entry()
        first = import_legacy()
        second = import_legacy()
        self.assertEqual(first["reports_created"], 1)
        self.assertEqual(second["reports_existing"], 1)
        self.assertNotIn("reports_created", second)
        self.assertEqual(PriceReport.objects.count(), 1)
        self.assertEqual(Place.objects.count(), 2)

    def test_dry_run_saves_nothing(self):
        self.entry()
        stats = import_legacy(dry_run=True)
        self.assertEqual(stats["reports_created"], 1)
        self.assertEqual(PriceReport.objects.count(), 0)
        self.assertEqual(Place.objects.count(), 0)

    def test_unit_conflict_with_existing_product_is_skipped_not_overwritten(self):
        cat = Category.objects.create(name="Boshqa", slug="boshqa")
        Product.objects.create(name="Mol go'shti", category=cat, default_unit="dona")
        self.entry()
        stats = import_legacy()
        self.assertEqual(stats["products_unit_conflict"], 1)
        self.assertEqual(stats["reports_skipped_unit_conflict"], 1)
        self.assertEqual(Product.objects.get(name="Mol go'shti").default_unit, "dona")
        self.assertEqual(PriceReport.objects.count(), 0)

    def test_city_option_puts_everything_in_one_city(self):
        City.objects.create(name="Namangan", slug="namangan")
        self.entry()
        import_legacy(city_slug="namangan")
        self.assertEqual({p.city.slug for p in Place.objects.all()}, {"namangan"})
        self.assertEqual(City.objects.count(), 1)

    def test_phone_copied_only_when_valid_and_unused(self):
        legacy.Profile.objects.filter(user=self.user).update(phone="90 123 45 67")
        legacy.Profile.objects.filter(user=self.voter).update(phone="not a phone")
        stats = import_legacy()
        self.assertEqual(UserProfile.objects.get(user=self.user).phone, "+998901234567")
        self.assertIsNone(UserProfile.objects.get(user=self.voter).phone)
        self.assertEqual((stats["phones_copied"], stats["phones_invalid"]), (1, 1))

    def test_legacy_rows_are_untouched(self):
        self.entry()
        before = legacy.PriceEntry.objects.count()
        import_legacy()
        self.assertEqual(legacy.PriceEntry.objects.count(), before)

    def test_command_runs(self):
        self.entry()
        call_command("import_legacy_prices", "--dry-run", stdout=__import__("io").StringIO())
        self.assertEqual(PriceReport.objects.count(), 0)
