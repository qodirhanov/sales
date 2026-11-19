"""Status transitions, trust, points, badges, expiry and admin actions."""
from datetime import timedelta

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.reports.models import PriceReport
from apps.verification import constants as C
from apps.verification import services
from apps.verification.errors import VerificationError

from .base import VerificationTestCase

Status = PriceReport.Status
Badge = UserProfile.Badge
User = get_user_model()


class TrustAndPointsTests(VerificationTestCase):
    def test_confirmed_report_rewards_the_author(self):
        author = self.make_user("author", trust=50)
        report = self.submit(author).report
        self.confirm_by(report, self.users(3))
        self.refresh(author.userprofile, report)
        self.assertEqual(author.userprofile.trust_score, 50 + C.TRUST_GAIN_CONFIRMED)
        self.assertEqual(author.userprofile.points, C.POINTS_PER_REPORT + C.POINTS_REPORT_CONFIRMED)
        self.assertEqual(report.points_awarded, C.POINTS_PER_REPORT + C.POINTS_REPORT_CONFIRMED)

    def test_rejection_lowers_trust_but_not_below_zero(self):
        author = self.make_user("bad", trust=3)
        report = self.submit(author).report
        services.reject_report(report)
        self.refresh(author.userprofile)
        self.assertEqual(author.userprofile.trust_score, 0)

    def test_trust_never_exceeds_100(self):
        author = self.make_user("top", trust=99)
        report = self.submit(author).report
        self.confirm_by(report, self.users(1))                              # trust 99 needs just 1
        self.refresh(author.userprofile)
        self.assertEqual(author.userprofile.trust_score, 100)

    def test_confirming_and_rejecting_are_idempotent(self):
        author = self.make_user("idem", trust=50)
        report = self.submit(author).report
        services.mark_confirmed(report)
        services.mark_confirmed(report)
        services.reject_report(report)
        services.reject_report(report)
        self.refresh(author.userprofile)
        self.assertEqual(author.userprofile.trust_score, 50 + C.TRUST_GAIN_CONFIRMED - C.TRUST_LOSS_REJECTED)


class BadgeTests(VerificationTestCase):
    def test_badge_thresholds(self):
        self.assertEqual(services.badge_for(50, 0), Badge.NEWCOMER)
        self.assertEqual(services.badge_for(50, C.BADGE_REGULAR_POINTS), Badge.REGULAR)
        self.assertEqual(services.badge_for(70, C.BADGE_TRUSTED_POINTS), Badge.TRUSTED)
        self.assertEqual(services.badge_for(69, C.BADGE_TRUSTED_POINTS), Badge.REGULAR)   # trust too low
        self.assertEqual(services.badge_for(90, C.BADGE_EXPERT_POINTS), Badge.EXPERT)
        self.assertEqual(services.badge_for(89, C.BADGE_EXPERT_POINTS), Badge.TRUSTED)

    def test_badge_is_updated_when_points_cross_a_threshold(self):
        user = self.make_user("climber", points=C.BADGE_REGULAR_POINTS - C.POINTS_PER_REPORT)
        self.submit(user)
        self.refresh(user.userprofile)
        self.assertEqual(user.userprofile.badge, Badge.REGULAR)


class ExpiryTests(VerificationTestCase):
    def setUp(self):
        self.seed_reports([100000] * 3)

    def test_unvouched_flagged_reports_expire_after_48_hours(self):
        t0 = timezone.now()
        old = self.submit(price=400000, now=t0).report
        self.assertEqual(old.status, Status.FLAGGED)
        self.assertEqual(services.expire_flagged(now=t0 + timedelta(hours=47)), 0)
        self.assertEqual(services.expire_flagged(now=t0 + timedelta(hours=48)), 1)
        self.refresh(old)
        self.assertEqual(old.status, Status.REJECTED)

    def test_expiry_only_touches_flagged_reports(self):
        t0 = timezone.now()
        pending = self.submit(price=100000, now=t0).report
        services.expire_flagged(now=t0 + timedelta(days=30))
        self.refresh(pending)
        self.assertEqual(pending.status, Status.PENDING)


class SubmitValidationTests(VerificationTestCase):
    def test_incompatible_unit_is_a_validation_error_and_creates_nothing(self):
        with self.assertRaises(ValidationError):
            self.submit(unit="litr")                                         # litres for a kg product
        self.assertEqual(PriceReport.objects.count(), 0)

    def test_domain_errors_share_a_base_class_and_carry_stable_codes(self):
        from apps.verification import errors
        codes = {e.code for e in (errors.RateLimited, errors.SelfConfirmation,
                                  errors.AlreadyConfirmed, errors.ReportClosed)}
        self.assertEqual(len(codes), 4)
        self.assertTrue(issubclass(errors.RateLimited, VerificationError))


class AdminActionTests(VerificationTestCase):
    def run_action(self, name, reports):
        admin = site._registry[PriceReport]
        request = RequestFactory().post("/")
        request.user = User.objects.get_or_create(username="root", defaults={"is_staff": True, "is_superuser": True})[0]
        request._messages = type("M", (), {"add": lambda *a, **k: None})()
        getattr(admin, name)(request, PriceReport.objects.filter(pk__in=[r.pk for r in reports]))

    def test_admin_confirm_and_reject_go_through_the_services(self):
        a, b = self.make_user("a", trust=50), self.make_user("b", trust=50)
        r1, r2 = self.submit(a).report, self.submit(b).report
        self.run_action("mark_confirmed", [r1])
        self.run_action("mark_rejected", [r2])
        self.refresh(r1, r2, a.userprofile, b.userprofile)
        self.assertEqual((r1.status, r2.status), (Status.CONFIRMED, Status.REJECTED))
        self.assertEqual(a.userprofile.trust_score, 50 + C.TRUST_GAIN_CONFIRMED)
        self.assertEqual(b.userprofile.trust_score, 50 - C.TRUST_LOSS_REJECTED)
