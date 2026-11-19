"""v2 write API (submit a price, confirm one) and the pages that depend on it, with USE_NEW_API on."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.catalog.models import Place, Product
from apps.reports.models import Confirmation, PriceReport

from .tests import ParityBase

User = get_user_model()


class WriteBase(ParityBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.newbie = User.objects.create_user("newbie", password="pw")
        cls.place = Place.objects.get(name="Chorsu bozori")     # has coordinates 41.0, 71.67
        cls.meat2 = Product.objects.get(name="Mol go'shti")
        cls.oil2 = Product.objects.get(name="Paxta yog'i")

    def setUp(self):
        cache.clear()  # throttle counters live in the cache and user ids repeat between tests
        self.client = APIClient()
        self.client.force_authenticate(self.newbie)

    def post(self, **over):
        body = {"product": self.meat2.pk, "location": self.place.pk, "price": 98000, "quantity": 1, "unit": "kg"}
        body.update(over)
        return self.client.post("/api/v2/prices/", body, format="json")


class SubmitTests(WriteBase):
    def test_requires_login(self):
        r = APIClient().post("/api/v2/prices/", {}, format="json")
        self.assertIn(r.status_code, (401, 403))

    def test_any_logged_in_user_can_submit_and_starts_pending(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.json())
        report = PriceReport.objects.get(pk=r.json()["id"])
        self.assertEqual((report.user, report.status, report.unit, report.price),
                         (self.newbie, "pending", "kg", 98000))

    def test_without_location_it_is_far_and_earns_no_points(self):
        body = self.post().json()
        self.assertTrue(body["is_far"])
        self.assertEqual(body["points_awarded"], 0)

    def test_with_nearby_location_it_earns_points(self):
        body = self.post(lat="41.000100", lng="71.670100").json()
        self.assertFalse(body["is_far"])
        self.assertEqual(body["points_awarded"], 5)
        self.assertLess(body["distance_m"], 50)

    def test_far_location_is_marked_far(self):
        self.assertTrue(self.post(lat="40.5", lng="71.0").json()["is_far"])

    def test_legacy_unit_codes_are_translated(self):
        r = self.post(product=self.oil2.pk, unit="l", price=9000)
        self.assertEqual(r.status_code, 201, r.json())
        self.assertEqual(PriceReport.objects.get(pk=r.json()["id"]).unit, "litr")
        eggs = Product.objects.get(name="Tuxum")
        r = self.post(product=eggs.pk, unit="piece", price=1000)
        self.assertEqual(PriceReport.objects.get(pk=r.json()["id"]).unit, "dona")

    def test_incompatible_unit_is_a_400_on_the_unit_field(self):
        r = self.post(product=self.oil2.pk, unit="g")
        self.assertEqual(r.status_code, 400)
        self.assertIn("unit", r.json())

    def test_validation_errors(self):
        self.assertEqual(self.post(price=0).status_code, 400)
        self.assertEqual(self.post(quantity=0).status_code, 400)
        self.assertEqual(self.post(unit="barrel").status_code, 400)
        self.assertEqual(self.post(product=999999).status_code, 400)
        self.assertEqual(self.post(lat="41.0").status_code, 400)                      # lat without lng
        self.assertEqual(self.post(source_url="javascript:alert(1)").status_code, 400)
        self.assertEqual(PriceReport.objects.filter(user=self.newbie).count(), 0)

    def test_promo_needs_a_higher_old_price_and_keeps_the_link(self):
        self.assertEqual(self.post(is_promo=True, old_price=90000).status_code, 400)
        r = self.post(is_promo=True, old_price=120000, source_url="https://shop.example/x")
        self.assertEqual(r.status_code, 201, r.json())
        report = PriceReport.objects.get(pk=r.json()["id"])
        self.assertEqual((report.is_promo, report.old_price, report.source_url), (True, 120000, "https://shop.example/x"))

    def test_old_price_is_dropped_when_not_a_promo(self):
        r = self.post(is_promo=False, old_price=120000)
        self.assertIsNone(PriceReport.objects.get(pk=r.json()["id"]).old_price)

    def test_second_report_for_same_place_and_product_is_rate_limited(self):
        self.assertEqual(self.post().status_code, 201)
        r = self.post(price=99000)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["code"], "rate_limited")
        self.assertGreater(r.json()["retry_after_seconds"], 0)

    def test_far_off_price_is_flagged_and_hidden_from_lists(self):
        r = self.post(price=400000)             # median is ~100 000, deviation far above 40%
        self.assertEqual(r.json()["status"], "flagged")
        cheapest = self.client.get(f"/api/v2/products/{self.meat2.pk}/cheapest/?days=30").json()["results"]
        self.assertNotIn(400000, [int(float(x["price"])) for x in cheapest])

    def test_response_shows_what_others_reported(self):
        ctx = self.post().json()["context"]
        self.assertGreater(ctx["count"], 0)
        self.assertIsNotNone(ctx["median"])


class ConfirmTests(WriteBase):
    def setUp(self):
        super().setUp()
        self.report_id = self.post().json()["id"]           # newbie's pending report
        self.voters = [User.objects.create_user(f"v{i}", password="pw") for i in range(3)]

    def vote(self, user, pk=None):
        c = APIClient()
        if user:
            c.force_authenticate(user)
        return c.post(f"/api/v2/prices/{pk or self.report_id}/confirm/")

    def test_requires_login(self):
        self.assertIn(self.vote(None).status_code, (401, 403))

    def test_author_cannot_confirm_own_report(self):
        r = self.vote(self.newbie)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["code"], "self_confirmation")

    def test_confirm_once_then_idempotent(self):
        first = self.vote(self.voters[0])
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["confirmations"], 1)
        again = self.vote(self.voters[0])
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["confirmations"], 1)

    def test_three_confirmations_make_it_confirmed(self):
        results = [self.vote(v).json() for v in self.voters]
        self.assertEqual(results[-1]["status"], "confirmed")
        self.assertTrue(results[-1]["became_confirmed"])
        self.assertEqual(PriceReport.objects.get(pk=self.report_id).status, "confirmed")

    def test_rejected_report_cannot_be_confirmed(self):
        PriceReport.objects.filter(pk=self.report_id).update(status="rejected")
        self.assertEqual(self.vote(self.voters[0]).status_code, 409)

    def test_unknown_report_is_404(self):
        self.assertEqual(self.vote(self.voters[0], pk=999999).status_code, 404)


@override_settings(USE_NEW_API=True)
class PagesOnNewWritesTests(WriteBase):
    def setUp(self):
        super().setUp()
        self.viewer = User.objects.create_user("viewer", password="pw")
        self.pending = self.post().json()["id"]
        self.odd_place = Place.objects.get(name="Yangi bozor")
        self.flagged = self.post(location=self.odd_place.pk, price=400000).json()["id"]

    def test_add_form_is_shown_again(self):
        self.client.force_login(self.newbie)
        self.assertContains(self.client.get("/"), 'id="add-form"')

    def test_confirm_page_needs_login(self):
        r = self.client.get("/tasdiqlash/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_confirm_page_lists_others_reports_flagged_first(self):
        self.client.force_login(self.viewer)
        r = self.client.get("/tasdiqlash/")
        self.assertEqual(r.status_code, 200)
        ids = [i["entry"].pk for i in r.context["items"]]
        self.assertEqual(ids[0], self.flagged)                 # suspicious first
        self.assertIn(self.pending, ids)
        self.assertContains(r, "400 000")
        self.assertContains(r, "Narx to'g'rimi?")
        self.assertIn("kishi kerak", r.content.decode())       # a flagged one says how many are still needed

    def test_confirm_page_hides_own_and_already_confirmed(self):
        APIClient()
        voter = APIClient()
        voter.force_authenticate(self.viewer)
        voter.post(f"/api/v2/prices/{self.pending}/confirm/")
        self.client.force_login(self.viewer)
        ids = [i["entry"].pk for i in self.client.get("/tasdiqlash/").context["items"]]
        self.assertNotIn(self.pending, ids)
        self.client.force_login(self.newbie)
        own = [i["entry"].pk for i in self.client.get("/tasdiqlash/").context["items"]]
        self.assertNotIn(self.pending, own)
        self.assertEqual(self.client.get("/tasdiqlash/").context["my_confirmed"], 0)

    def test_confirm_page_counts_my_confirmations(self):
        voter = APIClient()
        voter.force_authenticate(self.viewer)
        voter.post(f"/api/v2/prices/{self.pending}/confirm/")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/tasdiqlash/").context["my_confirmed"], 1)

    def test_confirm_page_js_posts_to_the_active_api(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get("/tasdiqlash/"), 'NK.API_READ + "prices/"')

    def test_settings_page_counts_new_reports(self):
        self.client.force_login(self.newbie)
        r = self.client.get("/settings/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["my_entries_count"], 2)
        self.assertEqual(len(r.context["recent_entries"]), 2)
        self.assertContains(r, "Mol go")
