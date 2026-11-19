"""Rule 5: one report per user + place + product per 6 hours."""
from datetime import timedelta

from django.utils import timezone

from apps.reports.models import PriceReport
from apps.verification import services
from apps.verification.errors import RateLimited

from .base import VerificationTestCase


class RateLimitTests(VerificationTestCase):
    def setUp(self):
        self.user = self.make_user("writer")
        self.t0 = timezone.now()
        self.submit(self.user, now=self.t0)

    def test_second_report_within_six_hours_is_refused(self):
        with self.assertRaises(RateLimited) as ctx:
            self.submit(self.user, now=self.t0 + timedelta(hours=5, minutes=59))
        self.assertAlmostEqual(ctx.exception.retry_after.total_seconds(), 60, delta=1)
        self.assertEqual(PriceReport.objects.filter(user=self.user).count(), 1)

    def test_allowed_again_after_six_hours(self):
        self.submit(self.user, now=self.t0 + timedelta(hours=6, seconds=1))
        self.assertEqual(PriceReport.objects.filter(user=self.user).count(), 2)

    def test_exactly_six_hours_later_is_allowed(self):
        self.submit(self.user, now=self.t0 + timedelta(hours=6))
        self.assertEqual(PriceReport.objects.filter(user=self.user).count(), 2)

    def test_other_place_other_product_and_other_user_are_independent(self):
        soon = self.t0 + timedelta(minutes=30)
        self.submit(self.user, place=self.place2, now=soon)                            # other place
        self.submit(self.user, product=self.oil, unit="litr", now=soon)                # other product
        self.submit(self.make_user("someone-else"), now=soon)                          # other user
        self.assertEqual(PriceReport.objects.count(), 4)

    def test_refused_attempt_leaves_no_trace_and_no_points(self):
        self.user.userprofile.refresh_from_db()
        points = self.user.userprofile.points
        with self.assertRaises(RateLimited):
            self.submit(self.user, now=self.t0 + timedelta(hours=1))
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.userprofile.points, points)

    def test_rejected_report_still_counts_toward_the_limit(self):
        """Otherwise a user could resubmit endlessly after being rejected."""
        services.reject_report(PriceReport.objects.get(user=self.user))
        with self.assertRaises(RateLimited):
            self.submit(self.user, now=self.t0 + timedelta(hours=1))

    def test_check_rate_limit_can_be_used_before_showing_a_form(self):
        with self.assertRaises(RateLimited):
            services.check_rate_limit(self.user, self.place, self.meat, now=self.t0 + timedelta(hours=1))
        services.check_rate_limit(self.user, self.place2, self.meat, now=self.t0 + timedelta(hours=1))
