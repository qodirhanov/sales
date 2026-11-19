"""Rule 1: reporter more than 500 m from the place -> accepted, but no points and lower trust weight."""
from decimal import Decimal

from apps.reports.models import PriceReport
from apps.verification import constants as C
from apps.verification import services

from .base import FAR_LAT, NEAR_LAT, PLACE_LAT, PLACE_LNG, VerificationTestCase


class HaversineTests(VerificationTestCase):
    def test_known_distances(self):
        self.assertAlmostEqual(services.haversine_m(PLACE_LAT, PLACE_LNG, PLACE_LAT, PLACE_LNG), 0, places=3)
        self.assertAlmostEqual(services.haversine_m(PLACE_LAT, PLACE_LNG, NEAR_LAT, PLACE_LNG), 489, delta=3)
        self.assertAlmostEqual(services.haversine_m(PLACE_LAT, PLACE_LNG, FAR_LAT, PLACE_LNG), 511, delta=3)


class DistanceRuleTests(VerificationTestCase):
    def test_near_report_gets_points_and_is_not_far(self):
        user = self.make_user("near")
        report = self.submit(user, near=True).report
        self.assertFalse(report.is_far)
        self.assertLessEqual(report.distance_m, C.MAX_DISTANCE_M)
        self.assertEqual(report.points_awarded, C.POINTS_PER_REPORT)
        self.refresh(user.userprofile)
        self.assertEqual(user.userprofile.points, C.POINTS_PER_REPORT)

    def test_far_report_is_accepted_without_points(self):
        user = self.make_user("far")
        report = self.submit(user, near=False, reporter_lat=FAR_LAT, reporter_lng=PLACE_LNG).report
        self.assertTrue(report.is_far)
        self.assertGreater(report.distance_m, C.MAX_DISTANCE_M)
        self.assertEqual(report.status, PriceReport.Status.PENDING)   # still accepted
        self.assertEqual(report.points_awarded, 0)
        self.refresh(user.userprofile)
        self.assertEqual(user.userprofile.points, 0)

    def test_boundary_489_m_is_near_and_511_m_is_far(self):
        near = self.submit(self.make_user("a"), near=False, reporter_lat=NEAR_LAT, reporter_lng=PLACE_LNG).report
        far = self.submit(self.make_user("b"), near=False, reporter_lat=FAR_LAT, reporter_lng=PLACE_LNG).report
        self.assertFalse(near.is_far)
        self.assertTrue(far.is_far)

    def test_missing_reporter_location_counts_as_far(self):
        user = self.make_user("noloc")
        report = self.submit(user, near=False).report
        self.assertTrue(report.is_far)
        self.assertIsNone(report.distance_m)
        self.assertEqual(report.points_awarded, 0)

    def test_place_without_coordinates_is_not_held_against_the_reporter(self):
        self.place2.lat = self.place2.lng = None
        self.place2.save()
        report = self.submit(self.make_user("x"), place=self.place2, near=False,
                             reporter_lat=FAR_LAT, reporter_lng=PLACE_LNG).report
        self.assertFalse(report.is_far)
        self.assertIsNone(report.distance_m)

    def test_far_author_trust_counts_for_less(self):
        # Trust 100 would need just 1.0 weight; as a far reporter it is treated as 30 -> default 3.0.
        author = self.make_user("vip", trust=100)
        far = self.submit(author, near=False, reporter_lat=FAR_LAT, reporter_lng=PLACE_LNG).report
        self.assertEqual(services.required_weight(far, 100), C.CONFIRM_THRESHOLD)
        near = self.submit(self.make_user("vip2", trust=100), place=self.place2).report
        self.assertEqual(services.required_weight(near, 100), C.CONFIRM_THRESHOLD_EXPERT)

    def test_far_author_gains_less_trust_and_no_bonus_points_when_confirmed(self):
        author = self.make_user("farauthor", trust=50)
        report = self.submit(author, near=False, reporter_lat=FAR_LAT, reporter_lng=PLACE_LNG).report
        self.confirm_by(report, self.users(3))
        self.refresh(report, author.userprofile)
        self.assertEqual(report.status, PriceReport.Status.CONFIRMED)
        self.assertEqual(author.userprofile.trust_score, 50 + C.TRUST_GAIN_CONFIRMED_FAR)
        self.assertEqual(author.userprofile.points, 0)
