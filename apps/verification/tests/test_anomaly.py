"""Rule 2: more than +-40% from the 14-day product+city median -> flagged."""
from apps.reports.models import PriceReport

from .base import VerificationTestCase

Status = PriceReport.Status


class AnomalyRuleTests(VerificationTestCase):
    def setUp(self):
        self.seed_reports([100000, 100000, 100000])   # median 100 000 / kg

    def status_for(self, price, **kw):
        return self.submit(price=price, **kw).report.status

    def test_inside_the_band_is_pending(self):
        self.assertEqual(self.status_for(100000), Status.PENDING)

    def test_exactly_forty_percent_is_still_accepted(self):
        self.assertEqual(self.status_for(140000), Status.PENDING)
        self.assertEqual(self.status_for(60000), Status.PENDING)

    def test_just_beyond_forty_percent_is_flagged(self):
        self.assertEqual(self.status_for(141000), Status.FLAGGED)
        self.assertEqual(self.status_for(59000), Status.FLAGGED)

    def test_flagged_report_is_recorded_with_a_status_time(self):
        report = self.submit(price=300000).report
        self.assertEqual(report.status, Status.FLAGGED)
        self.assertIsNotNone(report.status_changed_at)

    def test_compares_price_per_unit_not_the_raw_price(self):
        # 50 000 for 500 g = 100 000 / kg -> normal, although 50 000 looks "too cheap" at face value.
        report = self.submit(price=50000, quantity=500, unit="g").report
        self.assertEqual(report.status, Status.PENDING)
        # 150 000 for 1 kg is a real outlier.
        self.assertEqual(self.status_for(150000), Status.FLAGGED)

    def test_needs_enough_samples_to_judge(self):
        PriceReport.objects.all().delete()
        self.seed_reports([100000, 100000])            # only 2 comparable reports
        self.assertEqual(self.status_for(500000), Status.PENDING)

    def test_old_reports_outside_14_days_are_ignored(self):
        PriceReport.objects.all().delete()
        self.seed_reports([100000, 100000, 100000], days_ago=15)
        self.assertEqual(self.status_for(500000), Status.PENDING)   # no recent samples -> no judgement

    def test_other_city_and_other_product_do_not_count(self):
        PriceReport.objects.all().delete()
        self.seed_reports([100000] * 3, place=self.far_place)       # other city
        self.seed_reports([100000] * 3, product=self.oil, unit="litr")  # other product
        self.assertEqual(self.status_for(500000), Status.PENDING)

    def test_rejected_and_flagged_reports_do_not_define_the_median(self):
        PriceReport.objects.all().delete()
        self.seed_reports([100000] * 3, status=Status.REJECTED)
        self.seed_reports([100000] * 3, status=Status.FLAGGED)
        self.assertEqual(self.status_for(500000), Status.PENDING)

    def test_a_flagged_report_does_not_poison_later_comparisons(self):
        self.assertEqual(self.status_for(500000), Status.FLAGGED)
        self.assertEqual(self.status_for(100000, user=self.make_user("second")), Status.PENDING)

    def test_median_is_robust_to_one_wild_value(self):
        PriceReport.objects.all().delete()
        self.seed_reports([100000, 100000, 100000, 900000])         # median still 100 000
        self.assertEqual(self.status_for(105000), Status.PENDING)
