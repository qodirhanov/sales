"""Rule 6 (anti-copying): others' prices are only revealed as the result of submitting your own."""
import inspect
from decimal import Decimal

from apps.reports.models import PriceReport
from apps.verification import services

from .base import VerificationTestCase

Status = PriceReport.Status


class RevealAfterSubmitTests(VerificationTestCase):
    def test_context_is_returned_only_with_a_submitted_report(self):
        self.seed_reports([90000, 100000, 110000])
        result = self.submit(price=100000)
        self.assertEqual(result.context["count"], 3)
        self.assertEqual(result.context["median"], Decimal("100000.00"))
        self.assertEqual((result.context["min"], result.context["max"]),
                         (Decimal("90000.00"), Decimal("110000.00")))
        self.assertEqual(result.context["yours_vs_median_pct"], Decimal("0.00"))

    def test_context_compares_your_price_with_the_median(self):
        self.seed_reports([100000, 100000, 100000])
        result = self.submit(price=120000)
        self.assertEqual(result.context["yours_vs_median_pct"], Decimal("20.00"))

    def test_own_report_is_not_part_of_its_own_context(self):
        result = self.submit(price=100000)
        self.assertEqual(result.context["count"], 0)
        self.assertIsNone(result.context["median"])

    def test_only_confirmed_recent_same_city_reports_are_revealed(self):
        self.seed_reports([50000], status=Status.PENDING)
        self.seed_reports([50000], status=Status.FLAGGED)
        self.seed_reports([50000], status=Status.REJECTED)
        self.seed_reports([50000], days_ago=8)                          # too old
        self.seed_reports([50000], place=self.far_place)                # other city
        self.seed_reports([80000])                                      # the only valid one
        context = self.submit(price=100000).context
        self.assertEqual((context["count"], context["median"]), (1, Decimal("80000.00")))

    def test_no_service_function_reveals_prices_without_a_report(self):
        """Structural guard: the only public entry point for peer prices takes a report. If someone adds
        a 'prices_for(product, place)' helper for the add-price form, this test makes them think twice."""
        public = {name for name, obj in inspect.getmembers(services, inspect.isfunction)
                  if not name.startswith("_") and obj.__module__ == services.__name__}
        revealing = {name for name in public if "context" in name or "peer" in name or "prices_for" in name}
        self.assertEqual(revealing, {"price_context"})
        first_param = next(iter(inspect.signature(services.price_context).parameters))
        self.assertEqual(first_param, "report")
