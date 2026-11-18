import datetime
import os
import tempfile
from io import StringIO

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.catalog.models import Category, City, Place, Product, ProductAlias

from .models import ProductStats, ReferencePrice


class StatsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Namangan", slug="namangan")
        cat = Category.objects.create(name="Go'sht", slug="gosht")
        cls.beef = Product.objects.create(name="Mol go'shti", category=cat, default_unit="kg")
        ProductAlias.objects.create(product=cls.beef, alias="govyadina")
        cls.place = Place.objects.create(name="Bozor", type="bazaar", city=cls.city)


class ProductStatsConstraintTests(StatsBase):
    def test_one_city_row_and_one_row_per_place(self):
        ProductStats.objects.create(product=self.beef, city=self.city)                       # city aggregate
        ProductStats.objects.create(product=self.beef, city=self.city, place=self.place)     # place row
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductStats.objects.create(product=self.beef, city=self.city)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductStats.objects.create(product=self.beef, city=self.city, place=self.place)


class ImportStatUzTests(StatsBase):
    def csv(self, text):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        fh.write(text)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def run_import(self, path, *extra):
        out, err = StringIO(), StringIO()
        call_command("import_statuz", "--file", path, *extra, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_imports_by_name_and_alias_and_skips_unknown(self):
        path = self.csv("product,date,min_price,max_price\n"
                        "Mol go'shti,2026-11-10,85000,100000\n"
                        "GOVYADINA,2026-11-11,86000,101000\n"
                        "Noma'lum mahsulot,2026-11-11,1000,2000\n")
        out, err = self.run_import(path, "--region", "Namangan viloyati")
        self.assertEqual(ReferencePrice.objects.count(), 2)
        self.assertIn("2 new", out)
        self.assertIn("Noma'lum mahsulot", err)
        ref = ReferencePrice.objects.get(date=datetime.date(2026, 11, 10))
        self.assertEqual((ref.product, ref.min_price, ref.max_price, ref.region, ref.source),
                         (self.beef, 85000, 100000, "Namangan viloyati", "csv"))

    def test_rerun_updates_instead_of_duplicating(self):
        path = self.csv("product,date,min_price,max_price\nMol go'shti,2026-11-10,85000,100000\n")
        self.run_import(path)
        path2 = self.csv("product,date,min_price,max_price\nMol go'shti,2026-11-10,90000,105000\n")
        out, _ = self.run_import(path2)
        self.assertEqual(ReferencePrice.objects.count(), 1)
        self.assertEqual(ReferencePrice.objects.get().min_price, 90000)
        self.assertIn("1 updated", out)

    def test_dry_run_writes_nothing(self):
        path = self.csv("product,date,min_price,max_price\nMol go'shti,2026-11-10,85000,100000\n")
        out, _ = self.run_import(path, "--dry-run")
        self.assertEqual(ReferencePrice.objects.count(), 0)
        self.assertIn("DRY RUN", out)

    def test_bad_rows_and_min_gt_max_fail_loudly(self):
        with self.assertRaises(CommandError):
            self.run_import(self.csv("product,date,min_price,max_price\nMol go'shti,not-a-date,1,2\n"))
        with self.assertRaises(CommandError):
            self.run_import(self.csv("product,date,min_price,max_price\nMol go'shti,2026-11-10,200,100\n"))
        self.assertEqual(ReferencePrice.objects.count(), 0)

    def test_live_source_is_a_clear_not_connected_error(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("import_statuz")
        self.assertIn("not connected", str(ctx.exception))
