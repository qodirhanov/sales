from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Category, City, Place, Product
from apps.reports.models import PriceReport
from apps.verification import services

User = get_user_model()

PLACE_LAT, PLACE_LNG = Decimal("40.998300"), Decimal("71.672600")
# 1 degree of latitude ~ 111.2 km, so 0.0044 deg ~ 489 m and 0.0046 deg ~ 511 m.
NEAR_LAT = PLACE_LAT + Decimal("0.0044")
FAR_LAT = PLACE_LAT + Decimal("0.0046")


class VerificationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Namangan", slug="namangan")
        cls.other_city = City.objects.create(name="Andijon", slug="andijon")
        cat = Category.objects.create(name="Go'sht", slug="gosht")
        cls.meat = Product.objects.create(name="Mol go'shti", category=cat, default_unit="kg")
        cls.oil = Product.objects.create(name="Yog'", category=cat, default_unit="litr")
        cls.place = Place.objects.create(name="Bozor A", type="bazaar", city=cls.city,
                                         lat=PLACE_LAT, lng=PLACE_LNG)
        cls.place2 = Place.objects.create(name="Bozor B", type="bazaar", city=cls.city,
                                          lat=PLACE_LAT, lng=PLACE_LNG)
        cls.far_place = Place.objects.create(name="Andijon bozori", type="bazaar", city=cls.other_city,
                                             lat=PLACE_LAT, lng=PLACE_LNG)
        cls.seeder = User.objects.create_user("seeder")  # owner of fixture reports

    # ----------------------------------------------------------------- helpers
    def make_user(self, name, trust=50, points=0):
        user = User.objects.create_user(name)  # no password: skips slow hashing
        profile = user.userprofile
        profile.trust_score, profile.points = trust, points
        profile.save()
        return user

    def users(self, n, trust=50, prefix="u"):
        return [self.make_user(f"{prefix}{i}", trust) for i in range(n)]

    def seed_reports(self, prices, product=None, place=None, status=PriceReport.Status.CONFIRMED,
                     days_ago=1, unit="kg", quantity=1):
        """Direct fixture rows (bypass the service, so no rate limit / points / anomaly side effects)."""
        out = []
        for price in prices:
            out.append(PriceReport.objects.create(
                product=product or self.meat, place=place or self.place, user=self.seeder, price=price,
                quantity=quantity, unit=unit, status=status,
                created_at=timezone.now() - timedelta(days=days_ago)))
        return out

    def submit(self, user=None, price=100000, product=None, place=None, near=True, photo=False, now=None, **kw):
        user = user or self.make_user(f"author{User.objects.count()}")
        params = dict(user=user, product=product or self.meat, place=place or self.place, price=price,
                      unit="kg", now=now)
        if near:
            params.update(reporter_lat=NEAR_LAT, reporter_lng=PLACE_LNG)
        if photo:
            params["photo"] = SimpleUploadedFile("p.jpg", b"fake-image-bytes", content_type="image/jpeg")
        params.update(kw)
        return services.submit_report(**params)

    def confirm_by(self, report, users):
        result = None
        for u in users:
            result = services.confirm_report(report, u)
        return result

    def refresh(self, *objs):
        for o in objs:
            o.refresh_from_db()
