from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from rest_framework.test import APIClient

from .models import PriceAlert, PriceEntry
from .services import haversine_km
from .tests import BaseData

User = get_user_model()


class ConfirmationTests(BaseData):
    def setUp(self):
        self.other = User.objects.create_user("other", password="pw")
        self.third = User.objects.create_user("third", password="pw")
        self.client = APIClient()

    def _flagged(self):
        for _ in range(3):
            self.make(price=100000)
        return self.make(price=400000)  # >50% away from the median -> flagged

    def test_requires_login(self):
        e = self.make()
        self.assertEqual(self.client.post(f"/api/prices/{e.pk}/confirm/").status_code, 403)

    def test_author_cannot_confirm_own_price(self):
        e = self.make()
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(f"/api/prices/{e.pk}/confirm/").status_code, 403)

    def test_confirm_is_idempotent_per_user(self):
        e = self.make()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f"/api/prices/{e.pk}/confirm/").status_code, 201)
        r = self.client.post(f"/api/prices/{e.pk}/confirm/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["confirmations"], 1)

    def test_two_confirmations_unflag(self):
        e = self._flagged()
        self.assertTrue(e.is_flagged)
        self.client.force_authenticate(self.other)
        self.assertTrue(self.client.post(f"/api/prices/{e.pk}/confirm/").data["is_flagged"])
        self.client.force_authenticate(self.third)
        r = self.client.post(f"/api/prices/{e.pk}/confirm/")
        self.assertFalse(r.data["is_flagged"])
        e.refresh_from_db()
        self.assertFalse(e.is_flagged)

    def test_list_shows_confirmation_count(self):
        e = self.make()
        self.client.force_authenticate(self.other)
        self.client.post(f"/api/prices/{e.pk}/confirm/")
        row = self.client.get("/api/prices/").data["results"][0]
        self.assertEqual(row["confirmations"], 1)


class NearestTests(BaseData):
    def setUp(self):
        self.loc_a.lat, self.loc_a.lng = Decimal("41.311100"), Decimal("69.279700")  # Tashkent centre
        self.loc_a.save()
        self.loc_b.lat, self.loc_b.lng = Decimal("39.654400"), Decimal("66.975800")  # Samarkand
        self.loc_b.save()
        self.make(location=self.loc_a, price=120000)
        self.make(location=self.loc_b, price=90000)
        self.make(location=self.loc_c, price=100000)  # no coordinates

    def get(self, **params):
        return self.client.get(f"/api/products/{self.meat.pk}/cheapest/", params)

    def test_haversine_known_distance(self):
        d = haversine_km(41.3111, 69.2797, 39.6544, 66.9758)
        self.assertAlmostEqual(d, 270, delta=15)

    def test_default_sort_is_price(self):
        ids = [r["location"]["id"] for r in self.get().data["results"]]
        self.assertEqual(ids, [self.loc_b.id, self.loc_c.id, self.loc_a.id])

    def test_sort_by_distance_puts_unknown_last(self):
        r = self.get(sort="distance", lat=41.31, lng=69.28).data["results"]
        self.assertEqual([x["location"]["id"] for x in r], [self.loc_a.id, self.loc_b.id, self.loc_c.id])
        self.assertLess(r[0]["distance_km"], 1)
        self.assertIsNone(r[2]["distance_km"])

    def test_max_km_filters(self):
        r = self.get(lat=41.31, lng=69.28, max_km=50).data["results"]
        self.assertEqual([x["location"]["id"] for x in r], [self.loc_a.id])

    def test_validation(self):
        self.assertEqual(self.get(sort="distance").status_code, 400)
        self.assertEqual(self.get(lat="abc", lng="1").status_code, 400)
        self.assertEqual(self.get(lat=95, lng=1).status_code, 400)
        self.assertEqual(self.get(sort="x").status_code, 400)
        self.assertEqual(self.get(max_km=5).status_code, 400)


class BasketTests(BaseData):
    def setUp(self):
        self.client = APIClient()  # JSON bodies need DRF's client
        # A: meat 100k, oil 20k.  B: meat 90k only.  C: meat 110k, oil 15k.
        self.make(self.meat, self.loc_a, 100000)
        self.make(self.oil, self.loc_a, 20000, unit="l")
        self.make(self.meat, self.loc_b, 90000)
        self.make(self.meat, self.loc_c, 110000)
        self.make(self.oil, self.loc_c, 15000, unit="l")

    def post(self, items):
        return self.client.post("/api/basket/compare/", {"items": items}, format="json")

    def test_complete_stores_ranked_by_total(self):
        r = self.post([{"product": self.meat.pk, "quantity": 2}, {"product": self.oil.pk, "quantity": 1}])
        self.assertEqual(r.status_code, 200)
        stores = r.data["stores"]
        # A: 220k, C: 235k (complete) ; B: partial last
        self.assertEqual([s["location"]["id"] for s in stores], [self.loc_a.id, self.loc_c.id, self.loc_b.id])
        self.assertEqual(stores[0]["total"], Decimal("220000.00"))
        self.assertTrue(stores[0]["complete"])
        self.assertFalse(stores[2]["complete"])
        self.assertEqual(stores[2]["missing"], [self.oil.pk])
        self.assertEqual(r.data["best_store"], self.loc_a.id)

    def test_split_total_is_cheapest_per_item(self):
        r = self.post([{"product": self.meat.pk, "quantity": 2}, {"product": self.oil.pk, "quantity": 1}])
        # meat 90k*2 (B) + oil 15k (C) = 195k; best single store 220k -> saving 25k
        self.assertEqual(r.data["split_total"], Decimal("195000.00"))
        self.assertEqual(r.data["split_saving"], Decimal("25000.00"))

    def test_duplicate_products_are_merged(self):
        r = self.post([{"product": self.meat.pk, "quantity": 1}, {"product": self.meat.pk, "quantity": 1}])
        self.assertEqual(r.data["stores"][0]["total"], Decimal("180000.00"))  # 2 kg at B

    def test_validation(self):
        self.assertEqual(self.post([]).status_code, 400)
        self.assertEqual(self.post([{"product": 999999, "quantity": 1}]).status_code, 400)
        self.assertEqual(self.post([{"product": self.meat.pk, "quantity": 0}]).status_code, 400)
        self.assertEqual(self.post([{"product": self.meat.pk, "quantity": "NaN"}]).status_code, 400)
        self.assertEqual(self.post([{"product": "x", "quantity": 1}]).status_code, 400)
        self.assertEqual(self.client.post("/api/basket/compare/", {"items": "no"}, format="json").status_code, 400)

    def test_flagged_entries_are_ignored(self):
        PriceEntry.objects.filter(location=self.loc_b).update(is_flagged=True)
        r = self.post([{"product": self.meat.pk, "quantity": 1}])
        self.assertNotIn(self.loc_b.id, [s["location"]["id"] for s in r.data["stores"]])


class AlertTests(BaseData):
    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user("buyer", password="pw", email="buyer@example.com")
        self.client.force_authenticate(self.buyer)

    def test_requires_login(self):
        self.assertEqual(APIClient().get("/api/alerts/").status_code, 403)

    def test_create_list_and_isolation(self):
        self.make(price=100000)
        r = self.client.post("/api/alerts/", {"product": self.meat.pk, "target_price": 95000}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(str(r.data["current_best"])), Decimal("100000.00"))
        self.assertFalse(r.data["is_reached"])
        self.assertEqual(len(self.client.get("/api/alerts/").data), 1)
        other = APIClient()
        other.force_authenticate(User.objects.create_user("x", password="pw"))
        self.assertEqual(len(other.get("/api/alerts/").data), 0)
        self.assertEqual(other.delete(f"/api/alerts/{r.data['id']}/").status_code, 404)

    def test_duplicate_and_bad_target_rejected(self):
        body = {"product": self.meat.pk, "target_price": 95000}
        self.assertEqual(self.client.post("/api/alerts/", body, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/alerts/", body, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/alerts/", {"product": self.oil.pk, "target_price": 0},
                                          format="json").status_code, 400)

    def run_check(self):
        out = StringIO()
        call_command("check_price_alerts", stdout=out)
        return out.getvalue()

    def test_command_fires_once_then_rearms(self):
        alert = PriceAlert.objects.create(user=self.buyer, product=self.meat, target_price=95000)
        self.make(price=100000)
        self.run_check()
        self.assertEqual(len(mail.outbox), 0)  # not reached

        self.make(location=self.loc_b, price=90000)
        self.run_check()
        self.assertEqual(len(mail.outbox), 1)
        alert.refresh_from_db()
        self.assertEqual(alert.last_notified_price, Decimal("90000.00"))
        self.assertIsNotNone(alert.triggered_at)

        self.run_check()
        self.assertEqual(len(mail.outbox), 1)  # same price: no repeat

        self.make(location=self.loc_b, price=80000)
        self.run_check()
        self.assertEqual(len(mail.outbox), 2)  # cheaper again: notify

    def test_inactive_alert_is_skipped(self):
        PriceAlert.objects.create(user=self.buyer, product=self.meat, target_price=95000, is_active=False)
        self.make(price=90000)
        self.run_check()
        self.assertEqual(len(mail.outbox), 0)


class SearchTests(BaseData):
    def names(self, q):
        r = self.client.get("/api/products/", {"search": q})
        self.assertEqual(r.status_code, 200)
        return [p["name"] for p in r.data["results"]]

    def test_case_insensitive_including_non_ascii(self):
        self.assertEqual(self.names("MOL"), ["Mol go'shti"])
        self.assertEqual(self.names("mOl Go'ShTi"), ["Mol go'shti"])

    def test_spaces_are_ignored(self):
        self.assertEqual(self.names("molgo'shti"), ["Mol go'shti"])
        self.assertEqual(self.names("  mol   go'shti  "), ["Mol go'shti"])
        self.assertEqual(self.names("paxta yog'i"), ["Paxta yog'i"])
        self.assertEqual(self.names("paxtayogi"), ["Paxta yog'i"])

    def test_word_order_does_not_matter(self):
        self.assertEqual(self.names("go'shti mol"), ["Mol go'shti"])

    def test_every_apostrophe_style_and_none(self):
        for q in ("mol goshti", "mol go‘shti", "mol goʻshti", "mol goʼshti", "mol go`shti", "mol go’shti"):
            self.assertEqual(self.names(q), ["Mol go'shti"], q)

    def test_cyrillic_query(self):
        self.assertEqual(self.names("мол гўшти"), ["Mol go'shti"])
        self.assertEqual(self.names("пахта"), ["Paxta yog'i"])

    def test_small_typo_still_finds_product(self):
        self.assertEqual(self.names("mol goshtii"), ["Mol go'shti"])

    def test_no_match_is_empty_not_error(self):
        self.assertEqual(self.names("qqqqqq"), [])

    def test_blank_search_returns_everything(self):
        self.assertEqual(len(self.names("")), 2)
        self.assertEqual(len(self.names("   ")), 2)

    def test_search_key_follows_renames(self):
        self.meat.name = "Qo'y go'shti"
        self.meat.save()
        self.meat.refresh_from_db()
        self.assertEqual(self.meat.search_key, "qoygoshti")
        self.assertEqual(self.names("QOY"), ["Qo'y go'shti"])
        self.assertEqual(self.names("mol"), [])

    def test_page_size_param_returns_whole_catalogue(self):
        from .models import Product
        for i in range(25):
            Product.objects.create(name=f"Mahsulot {i}", category=self.meat.category, base_unit="kg")
        self.assertEqual(len(self.client.get("/api/products/").data["results"]), 20)
        self.assertEqual(len(self.client.get("/api/products/", {"page_size": 200}).data["results"]), 27)


class PrefixRankingTests(BaseData):
    def test_names_starting_with_query_come_first(self):
        from .models import Product
        cat = self.meat.category
        Product.objects.create(name="Qo'l sumka", category=cat, base_unit="piece")
        Product.objects.create(name="Sumka", category=cat, base_unit="piece")
        Product.objects.create(name="Sumalak", category=cat, base_unit="kg")
        names = [p["name"] for p in self.client.get("/api/products/", {"search": "sum"}).data["results"]]
        self.assertEqual(names, ["Sumalak", "Sumka", "Qo'l sumka"])
        names = [p["name"] for p in self.client.get("/api/products/", {"search": "SUMK"}).data["results"]]
        self.assertEqual(names, ["Sumka", "Qo'l sumka"])
