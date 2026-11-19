"""Rules 3 and 4: independent confirmations (or 1 + photo); trust shortens the path."""
from decimal import Decimal

from apps.reports.models import PriceReport
from apps.verification import constants as C
from apps.verification import services
from apps.verification.errors import AlreadyConfirmed, ReportClosed, SelfConfirmation

from .base import VerificationTestCase

Status = PriceReport.Status


class ConfirmerWeightTests(VerificationTestCase):
    def test_weight_follows_trust_and_is_clamped(self):
        self.assertEqual(services.confirmer_weight(50), Decimal("1.00"))
        self.assertEqual(services.confirmer_weight(100), Decimal("2.00"))
        self.assertEqual(services.confirmer_weight(75), Decimal("1.50"))
        self.assertEqual(services.confirmer_weight(20), Decimal("0.40"))
        self.assertEqual(services.confirmer_weight(0), Decimal("0.40"))     # floor

    def test_confirmation_stores_the_weight_at_that_moment(self):
        report = self.submit().report
        voter = self.make_user("voter", trust=100)
        result = services.confirm_report(report, voter)
        self.assertEqual(result.confirmation.weight, Decimal("2.00"))
        voter.userprofile.trust_score = 10
        voter.userprofile.save()
        result.confirmation.refresh_from_db()
        self.assertEqual(result.confirmation.weight, Decimal("2.00"))       # history is not rewritten


class ThreeConfirmationsTests(VerificationTestCase):
    def test_two_confirmations_are_not_enough(self):
        report = self.submit().report
        self.confirm_by(report, self.users(2))
        self.refresh(report)
        self.assertEqual(report.status, Status.PENDING)

    def test_three_independent_confirmations_confirm(self):
        report = self.submit().report
        result = self.confirm_by(report, self.users(3))
        self.refresh(report)
        self.assertEqual(report.status, Status.CONFIRMED)
        self.assertTrue(result.became_confirmed)
        self.assertIsNotNone(report.status_changed_at)

    def test_low_trust_confirmers_cannot_reach_the_threshold_by_numbers_alone(self):
        report = self.submit().report
        self.confirm_by(report, self.users(5, trust=20, prefix="weak"))     # 5 x 0.4 = 2.0 < 3.0
        self.refresh(report)
        self.assertEqual(report.status, Status.PENDING)

    def test_two_high_trust_confirmers_are_worth_more_than_three_average_ones(self):
        report = self.submit().report
        self.confirm_by(report, self.users(2, trust=100, prefix="vip"))     # 2 x 2.0 = 4.0 >= 3.0
        self.refresh(report)
        self.assertEqual(report.status, Status.CONFIRMED)


class PhotoShortcutTests(VerificationTestCase):
    def test_one_confirmation_plus_photo_confirms(self):
        report = self.submit(photo=True).report
        self.confirm_by(report, self.users(1))
        self.refresh(report)
        self.assertEqual(report.status, Status.CONFIRMED)

    def test_photo_without_any_confirmation_stays_pending(self):
        report = self.submit(photo=True).report
        self.assertEqual(report.status, Status.PENDING)

    def test_one_confirmation_without_photo_is_not_enough(self):
        report = self.submit(photo=False).report
        self.confirm_by(report, self.users(1))
        self.refresh(report)
        self.assertEqual(report.status, Status.PENDING)


class TrustedAuthorTests(VerificationTestCase):
    def author_report(self, trust, name):
        return self.submit(self.make_user(name, trust=trust)).report

    def test_default_author_needs_three(self):
        self.assertEqual(services.required_weight(self.author_report(50, "a"), 50), C.CONFIRM_THRESHOLD)

    def test_trusted_author_needs_two_confirmations(self):
        report = self.author_report(70, "trusted")
        self.confirm_by(report, self.users(1))
        self.refresh(report)
        self.assertEqual(report.status, Status.PENDING)
        self.confirm_by(report, self.users(1, prefix="second"))
        self.refresh(report)
        self.assertEqual(report.status, Status.CONFIRMED)

    def test_expert_author_needs_a_single_confirmation(self):
        report = self.author_report(90, "expert")
        self.confirm_by(report, self.users(1))
        self.refresh(report)
        self.assertEqual(report.status, Status.CONFIRMED)

    def test_a_low_trust_confirmer_is_not_enough_even_for_an_expert(self):
        report = self.author_report(95, "expert2")
        self.confirm_by(report, self.users(1, trust=20, prefix="weak"))     # weight 0.4 < 1.0
        self.refresh(report)
        self.assertEqual(report.status, Status.PENDING)


class ConfirmationGuardTests(VerificationTestCase):
    def test_author_cannot_confirm_own_report(self):
        author = self.make_user("selfie")
        report = self.submit(author).report
        with self.assertRaises(SelfConfirmation):
            services.confirm_report(report, author)

    def test_same_user_cannot_confirm_twice_so_confirmations_must_be_independent(self):
        report = self.submit().report
        voter = self.make_user("repeat")
        services.confirm_report(report, voter)
        with self.assertRaises(AlreadyConfirmed):
            services.confirm_report(report, voter)
        self.assertEqual(report.confirmations.count(), 1)

    def test_rejected_report_cannot_be_confirmed(self):
        report = self.submit().report
        services.reject_report(report)
        with self.assertRaises(ReportClosed):
            services.confirm_report(report, self.make_user("late"))

    def test_late_confirmation_of_a_confirmed_report_gives_no_points(self):
        report = self.submit(self.make_user("auth", trust=95)).report
        self.confirm_by(report, self.users(1))                              # confirmed by the first
        late = self.make_user("late2")
        services.confirm_report(report, late)
        self.refresh(late.userprofile)
        self.assertEqual(late.userprofile.points, 0)
        self.assertEqual(report.confirmations.count(), 2)

    def test_confirmer_earns_a_point_for_an_open_report(self):
        report = self.submit().report
        voter = self.make_user("pointy")
        services.confirm_report(report, voter)
        self.refresh(voter.userprofile)
        self.assertEqual(voter.userprofile.points, C.POINTS_PER_CONFIRMATION)


class FlaggedRecoveryTests(VerificationTestCase):
    def setUp(self):
        self.seed_reports([100000] * 3)

    def flagged(self, **kw):
        report = self.submit(price=400000, **kw).report
        self.assertEqual(report.status, Status.FLAGGED)
        return report

    def test_flagged_needs_full_weight_and_ignores_the_photo_shortcut(self):
        report = self.flagged(photo=True)
        self.confirm_by(report, self.users(1))
        self.refresh(report)
        self.assertEqual(report.status, Status.FLAGGED)                      # photo does not help
        self.confirm_by(report, self.users(2, prefix="more"))
        self.refresh(report)
        self.assertEqual(report.status, Status.CONFIRMED)

    def test_flagged_ignores_the_author_trust_discount(self):
        report = self.flagged(user=self.make_user("expert", trust=95))
        self.confirm_by(report, self.users(1))
        self.refresh(report)
        self.assertEqual(report.status, Status.FLAGGED)
