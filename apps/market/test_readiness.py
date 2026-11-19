from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import City, Place
from apps.reports.models import PriceReport

from .readiness import run_checks
from .testing import MarketBase


def levels(checks):
    return [level for level, _ in checks]


class ReadinessTests(MarketBase):
    def test_fixture_is_ready_with_a_warning_about_coordinates(self):
        checks = run_checks()
        self.assertNotIn("fail", levels(checks))
        self.assertTrue(any("no coordinates" in m for _, m in checks))   # two of three places have none

    def test_all_coordinates_present_clears_the_warning(self):
        Place.objects.filter(lat__isnull=True).update(lat="41.1", lng="71.1")
        self.assertFalse(any("no coordinates" in m for _, m in run_checks()))

    def test_no_reports_is_only_a_warning(self):
        PriceReport.objects.all().delete()
        checks = run_checks()
        self.assertNotIn("fail", levels(checks))
        self.assertTrue(any("No price reports" in m for _, m in checks))

    def test_command_prints_and_exits_nonzero_on_failure(self):
        out = StringIO()
        call_command("check_setup", stdout=out)
        self.assertIn("[WARN]", out.getvalue())
        PriceReport.objects.all().delete()
        Place.objects.all().delete()
        with self.assertRaises(SystemExit) as cm:
            call_command("check_setup", stdout=StringIO())
        self.assertEqual(cm.exception.code, 1)


class EmptyDatabaseTests(TestCase):
    def test_no_city_products_or_places_fails(self):
        City.objects.all().delete()
        msgs = [m for level, m in run_checks() if level == "fail"]
        self.assertTrue(any("No city" in m for m in msgs))
        self.assertTrue(any("No active products" in m for m in msgs))
        self.assertTrue(any("No active places" in m for m in msgs))
