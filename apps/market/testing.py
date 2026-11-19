"""Shared fixture for the market tests (not a test module itself).

Three products at three places in one city, with a small price history:
  Mol go'shti (kg)   Chorsu 90 000 five days ago -> 99 000 now; Mega 100 000 four days ago -> 70 000 now;
                     Yangi bozor 50 000 for 500 g (= 100 000 / kg)
  Paxta yog'i (litr) Chorsu 16 000 for 2 l (= 8 000 / l); Mega 9 000 / l on promo (was 12 000), with a link
  Tuxum (dona)       Chorsu 30 000 for 30 pieces (= 1 000 each)
Only Chorsu bozori has coordinates.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Category, City, Place, Product
from apps.reports.models import PriceReport

User = get_user_model()


class MarketBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("seller", password="pw")
        cls.voter = User.objects.create_user("voter", password="pw")
        cat = Category.objects.create(name="Go'sht", slug="gosht")
        cls.meat = Product.objects.create(name="Mol go'shti", category=cat, default_unit="kg")
        cls.oil = Product.objects.create(name="Paxta yog'i", category=cat, default_unit="litr")
        cls.eggs = Product.objects.create(name="Tuxum", category=cat, default_unit="dona")
        city = City.objects.create(name="Namangan", slug="namangan")
        cls.city = city
        cls.a = Place.objects.create(name="Chorsu bozori", type="bazaar", city=city, lat="41.000000", lng="71.670000")
        cls.b = Place.objects.create(name="Mega do'kon", type="shop", city=city, website="https://mega.example")
        cls.c = Place.objects.create(name="Yangi bozor", type="bazaar", city=city)
        now = timezone.now()

        def report(product, place, price, quantity, unit, days=0, hours=0, **kw):
            return PriceReport.objects.create(
                product=product, place=place, user=cls.user, price=price, quantity=quantity, unit=unit,
                status="confirmed", created_at=now - timedelta(days=days, hours=hours), **kw)

        report(cls.meat, cls.a, 90000, 1, "kg", days=5)
        report(cls.meat, cls.a, 99000, 1, "kg", hours=2)
        report(cls.meat, cls.b, 100000, 1, "kg", days=4)
        report(cls.meat, cls.b, 70000, 1, "kg", hours=3)
        report(cls.meat, cls.c, 50000, 500, "g", hours=1)
        report(cls.oil, cls.a, 16000, 2, "litr", hours=4)
        report(cls.oil, cls.b, 9000, 1, "litr", hours=5, is_promo=True, old_price=12000,
               source_url="https://shop.example/oil")
        report(cls.eggs, cls.a, 30000, 30, "dona", hours=6)
        cls.api = APIClient()

    def product_named(self, name):
        return Product.objects.get(name=name)
