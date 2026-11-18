from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Category, City, Place, Product, ProductAlias
from .textnorm import normalize_text


class TextNormTests(TestCase):
    def test_forms_of_the_same_name_match(self):
        for q in ("Mol go'shti", "MOL GO‘SHTI", "molgoshti", "мол гўшти", "  mol   goʻshti "):
            self.assertEqual(normalize_text(q), "molgoshti", q)


class ModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Namangan", slug="namangan")
        cls.cat = Category.objects.create(name="Go'sht", slug="gosht")
        cls.beef = Product.objects.create(name="Mol go'shti", category=cls.cat, default_unit="kg")

    def test_search_key_follows_rename(self):
        self.assertEqual(self.beef.search_key, "molgoshti")
        self.beef.name = "Qo'y go'shti"
        self.beef.save(update_fields=["name"])
        self.beef.refresh_from_db()
        self.assertEqual(self.beef.search_key, "qoygoshti")

    def test_alias_is_normalised_and_unique_per_product(self):
        a = ProductAlias.objects.create(product=self.beef, alias="Govyadina")
        self.assertEqual(a.search_key, "govyadina")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductAlias.objects.create(product=self.beef, alias="GOVYADINA ")

    def test_pack_size_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(name="Un", category=self.cat, default_unit="kg", pack_size=Decimal("0"))

    def test_place_name_unique_per_city(self):
        Place.objects.create(name="Bozor", type="bazaar", city=self.city)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Place.objects.create(name="Bozor", type="shop", city=self.city)

    def test_place_needs_both_coordinates(self):
        p = Place(name="Do'kon", type="shop", city=self.city, lat=Decimal("40.99"))
        with self.assertRaises(ValidationError):
            p.clean()
        p.lng = Decimal("71.67")
        p.clean()


class SeedTests(TestCase):
    def run_seed(self):
        out = StringIO()
        call_command("seed_namangan", stdout=out)
        return out.getvalue()

    def test_seed_creates_25_products_and_8_places(self):
        Product.objects.all().delete()
        self.run_seed()
        self.assertEqual(Product.objects.count(), 25)
        self.assertEqual(Place.objects.filter(city__slug="namangan").count(), 8)
        self.assertTrue(Product.objects.get(name="Un (oliy nav)").pack_size == 50)

    def test_seed_is_idempotent(self):
        self.run_seed()
        counts = (Product.objects.count(), ProductAlias.objects.count(), Place.objects.count(), Category.objects.count())
        self.run_seed()
        self.assertEqual(counts, (Product.objects.count(), ProductAlias.objects.count(),
                                  Place.objects.count(), Category.objects.count()))

    def test_aliases_resolve_to_products(self):
        self.run_seed()
        hit = ProductAlias.objects.get(search_key="govyadina")
        self.assertEqual(hit.product.name, "Mol go'shti")
