from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.catalog.models import City, Place
from apps.reports.models import PriceReport

from .readiness import run_checks
from .tests import ParityBase


def levels(checks):
    return [level for level, _ in checks]


class ReadinessTests(ParityBase):
    def test_imported_data_is_ready_with_warnings_about_coordinates(self):
        checks = run_checks()
        self.assertNotIn("fail", levels(checks))
        self.assertTrue(any("no coordinates" in m for _, m in checks))   # two of three places have none

    def test_all_coordinates_present_clears_the_warning(self):
        Place.objects.filter(lat__isnull=True).update(lat="41.1", lng="71.1")
        Place.objects.filter(lng__isnull=True).update(lng="71.1")
        self.assertFalse(any("no coordinates" in m for _, m in run_checks()))

    def test_missing_import_is_a_failure(self):
        PriceReport.objects.all().delete()
        checks = run_checks()
        self.assertIn("fail", levels(checks))
        self.assertTrue(any("import_legacy_prices" in m for _, m in checks))

    def test_missing_products_are_a_failure(self):
        from apps.catalog.models import Product
        # a product with reports is protected, so remove its reports first to simulate a partial import
        PriceReport.objects.filter(product__name="Tuxum").delete()
        Product.objects.filter(name="Tuxum").delete()
        self.assertTrue(any(l == "fail" and "missing in the new catalog" in m for l, m in run_checks()))

    @override_settings(USE_NEW_API=True)
    def test_flag_state_is_reported(self):
        self.assertTrue(any(l == "ok" and "ON" in m for l, m in run_checks()))

    def test_command_prints_and_exits_nonzero_on_failure(self):
        out = StringIO()
        call_command("check_new_api_ready", stdout=out)
        self.assertIn("[WARN]", out.getvalue())
        PriceReport.objects.all().delete()
        with self.assertRaises(SystemExit) as cm:
            call_command("check_new_api_ready", stdout=StringIO())
        self.assertEqual(cm.exception.code, 1)


class EmptyDatabaseTests(TestCase):
    def test_no_city_or_places_fails(self):
        City.objects.all().delete()
        msgs = [m for l, m in run_checks() if l == "fail"]
        self.assertTrue(any("No city" in m for m in msgs))
        self.assertTrue(any("No active places" in m for m in msgs))
