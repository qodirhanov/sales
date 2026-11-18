from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.catalog.models import Category, City, Place, Product

from .models import Confirmation, PriceReport
from .units import compute_normalized_price

User = get_user_model()


class ReportBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        city = City.objects.create(name="Namangan", slug="namangan")
        cat = Category.objects.create(name="Test", slug="test")
        cls.meat = Product.objects.create(name="Mol go'shti", category=cat, default_unit="kg")
        cls.flour = Product.objects.create(name="Un", category=cat, default_unit="kg", pack_size=Decimal("50"))
        cls.oil = Product.objects.create(name="Yog'", category=cat, default_unit="litr")
        cls.eggs = Product.objects.create(name="Tuxum", category=cat, default_unit="dona", pack_size=Decimal("30"))
        cls.place = Place.objects.create(name="Bozor", type="bazaar", city=city)
        cls.user = User.objects.create_user("u", password="pw")
        cls.other = User.objects.create_user("o", password="pw")

    def report(self, product=None, price=100000, quantity=1, unit="kg", **kw):
        return PriceReport.objects.create(product=product or self.meat, place=self.place, user=self.user,
                                          price=price, quantity=quantity, unit=unit, **kw)


class NormalizationTests(ReportBase):
    def test_plain_and_gram_conversion(self):
        self.assertEqual(self.report(price=30000, quantity=500, unit="g").normalized_price, Decimal("60000.00"))
        self.assertEqual(self.report(price=95000, quantity=1, unit="kg").normalized_price, Decimal("95000.00"))

    def test_liters_and_millilitres(self):
        self.assertEqual(self.report(self.oil, 8000, 500, "ml").normalized_price, Decimal("16000.00"))

    def test_fifty_kg_sack_costs_per_kg(self):
        self.assertEqual(self.report(self.flour, 400000, 50, "kg").normalized_price, Decimal("8000.00"))

    def test_pack_unit_uses_product_pack_size(self):
        self.assertEqual(self.report(self.flour, 400000, 1, "qop").normalized_price, Decimal("8000.00"))
        self.assertEqual(self.report(self.eggs, 45000, 1, "qop").normalized_price, Decimal("1500.00"))

    def test_pack_unit_rejected_when_product_has_no_pack_size(self):
        with self.assertRaises(ValidationError):
            compute_normalized_price(self.meat, 100000, 1, "qop")

    def test_incompatible_unit_rejected(self):
        for product, unit in ((self.meat, "litr"), (self.oil, "g"), (self.eggs, "kg")):
            with self.assertRaises(ValidationError, msg=f"{product}/{unit}"):
                compute_normalized_price(product, 1000, 1, unit)

    def test_non_positive_quantity_rejected(self):
        with self.assertRaises(ValidationError):
            compute_normalized_price(self.meat, 1000, 0, "kg")


class ConstraintTests(ReportBase):
    def test_new_report_defaults_to_pending(self):
        r = self.report()
        self.assertEqual((r.status, r.is_far, r.points_awarded), (PriceReport.Status.PENDING, False, 0))

    def test_zero_price_is_blocked_by_the_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.report(price=0)

    def test_one_confirmation_per_user_per_report(self):
        r = self.report()
        Confirmation.objects.create(report=r, user=self.other)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Confirmation.objects.create(report=r, user=self.other)
        self.assertEqual(r.confirmations.count(), 1)

    def test_confirmation_weight_defaults_to_one(self):
        c = Confirmation.objects.create(report=self.report(), user=self.other)
        self.assertEqual(c.weight, Decimal("1.00"))
