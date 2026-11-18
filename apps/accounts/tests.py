from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from .models import UserProfile
from .phone import normalize_phone, validate_phone

User = get_user_model()


class PhoneTests(SimpleTestCase):
    def test_all_common_spellings_normalise_the_same(self):
        for raw in ("+998 90 123 45 67", "998901234567", "90 123 45 67", "(90) 123-45-67", "+998901234567"):
            self.assertEqual(normalize_phone(raw), "+998901234567", raw)

    def test_rejects_foreign_or_short_numbers(self):
        for raw in ("", None, "123", "+7 912 345 67 89", "99890123456", "+9989012345678"):
            with self.assertRaises(ValueError, msg=raw):
                normalize_phone(raw)
            with self.assertRaises(ValidationError, msg=raw):
                validate_phone(raw)


class ProfileTests(TestCase):
    def test_profile_is_created_with_defaults(self):
        u = User.objects.create_user("ali", password="pw")
        p = u.userprofile
        self.assertEqual((p.trust_score, p.points, p.badge), (50, 0, UserProfile.Badge.NEWCOMER))
        self.assertIsNone(p.phone)

    def test_phone_is_normalised_and_unique(self):
        a = User.objects.create_user("a", password="pw")
        b = User.objects.create_user("b", password="pw")
        a.userprofile.phone = "90 123 45 67"
        a.userprofile.save()
        a.userprofile.refresh_from_db()
        self.assertEqual(a.userprofile.phone, "+998901234567")
        b.userprofile.phone = "+998 90 123 45 67"
        with self.assertRaises(IntegrityError), transaction.atomic():
            b.userprofile.save()

    def test_many_users_without_phone_do_not_collide(self):
        for name in ("x", "y", "z"):
            User.objects.create_user(name, password="pw")
        self.assertEqual(UserProfile.objects.filter(phone__isnull=True).count(), 3)

    def test_trust_score_is_capped_at_100(self):
        p = User.objects.create_user("t", password="pw").userprofile
        p.trust_score = 101
        with self.assertRaises(ValidationError):
            p.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            p.save()
