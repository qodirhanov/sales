"""Read API (/api/), pages, alerts and content, on the fixture in testing.py."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog.models import Category, Place, Product, ProductAlias
from apps.reports.models import PriceReport

from .models import PriceAlert
from .testing import MarketBase


def D(value):
    return Decimal(str(value))


class CatalogApiTests(MarketBase):
    def test_products_list_shape_units_and_order(self):
        data = self.api.get("/api/products/?page_size=50").json()
        self.assertEqual([(p["name"], p["base_unit"], p["category_name"]) for p in data["results"]],
                         [("Mol go'shti", "kg", "Go'sht"), ("Paxta yog'i", "l", "Go'sht"), ("Tuxum", "piece", "Go'sht")])
        self.assertEqual(set(data["results"][0]),
                         {"id", "name", "category", "category_name", "base_unit", "is_active", "image",
                          "description", "usage"})

    def test_search_ignores_case_and_apostrophes_and_finds_typos(self):
        for q in ("mol go'sht", "MOLGOSHT", "mol goshtt"):
            names = [p["name"] for p in self.api.get("/api/products/", {"search": q}).json()["results"]]
            self.assertEqual(names, ["Mol go'shti"], q)

    def test_search_finds_aliases(self):
        ProductAlias.objects.create(product=self.meat, alias="govyadina")
        names = [p["name"] for p in self.api.get("/api/products/", {"search": "govyadina"}).json()["results"]]
        self.assertEqual(names, ["Mol go'shti"])

    def test_categories_districts_locations_shapes(self):
        cat = self.api.get("/api/categories/").json()[0]
        self.assertEqual(set(cat), {"id", "name", "slug", "emoji", "image", "parent", "product_count"})
        self.assertEqual(cat["product_count"], 3)
        self.assertEqual(self.api.get("/api/districts/").json()[0]["name"], "Namangan")
        places = self.api.get("/api/locations/?page_size=50").json()
        self.assertEqual(sorted(p["name"] for p in places["results"]),
                         ["Chorsu bozori", "Mega do'kon", "Yangi bozor"])
        self.assertEqual(set(places["results"][0]),
                         {"id", "name", "type", "district", "district_name", "address", "website", "lat", "lng",
                          "is_active"})

    def test_all_places_come_back_with_a_page_size(self):
        for i in range(25):
            Place.objects.create(name=f"Joy {i}", type="shop", city=self.city)
        data = self.api.get("/api/locations/?page_size=200").json()
        self.assertEqual((data["count"], len(data["results"])), (28, 28))
        self.assertEqual(len(self.api.get("/api/locations/").json()["results"]), 20)

    def test_home_asks_for_the_full_place_list(self):
        self.assertContains(self.client.get("/"), 'api("locations/?page_size=200")')

    def test_unit_codes_use_the_short_spelling(self):
        res = self.api.get(f"/api/products/{self.oil.pk}/cheapest/").json()["results"]
        self.assertEqual({r["unit"] for r in res}, {"l"})
        self.assertEqual(res[0]["base_unit"], "l")


class CheapestApiTests(MarketBase):
    def cheapest(self, product, query=""):
        return self.api.get(f"/api/products/{product.pk}/cheapest/{query}").json()["results"]

    def test_order_prices_links_and_changes(self):
        res = self.cheapest(self.meat, "?days=30")
        self.assertEqual([r["location"]["name"] for r in res], ["Mega do'kon", "Chorsu bozori", "Yangi bozor"])
        self.assertEqual([D(r["normalized_price"]) for r in res], [D("70000"), D("99000"), D("100000")])
        self.assertEqual([r["link_kind"] for r in res], ["store", "map", "map"])
        self.assertEqual([(r["change"] or {}).get("dir") for r in res], ["down", "up", None])
        self.assertEqual([(r["change"] or {}).get("pct") for r in res], [-30, 10, None])
        self.assertEqual(res[0]["link"], "https://mega.example")

    def test_grams_are_normalised_to_kg(self):
        res = self.cheapest(self.meat, "?days=30")
        self.assertEqual(D(res[-1]["normalized_price"]), D("100000"))

    def test_promo_and_source_link_survive(self):
        res = self.cheapest(self.oil)
        promo = next(r for r in res if r["is_promo"])
        self.assertEqual(promo["link"], "https://shop.example/oil")
        self.assertEqual(int(promo["old_price"]), 12000)

    def test_district_filter_is_the_city(self):
        city = self.api.get("/api/districts/").json()[0]["id"]
        self.assertEqual(len(self.cheapest(self.meat, f"?days=30&district={city}")), 3)
        self.assertEqual(self.cheapest(self.meat, "?days=30&district=999999"), [])

    def test_bad_params_are_rejected(self):
        self.assertEqual(self.api.get(f"/api/products/{self.eggs.pk}/cheapest/?days=0").status_code, 400)
        self.assertEqual(self.api.get(f"/api/products/{self.eggs.pk}/cheapest/?sort=distance").status_code, 400)

    def test_distance_sort_and_radius(self):
        res = self.cheapest(self.meat, "?days=30&lat=41.0&lng=71.67&sort=distance")
        self.assertEqual(res[0]["location"]["name"], "Chorsu bozori")      # the only place with coordinates
        near = self.cheapest(self.meat, "?days=30&lat=41.0&lng=71.67&max_km=1")
        self.assertEqual([r["location"]["name"] for r in near], ["Chorsu bozori"])


class DealsAndBasketTests(MarketBase):
    def test_deals(self):
        res = self.api.get("/api/deals/?limit=20").json()["results"]
        self.assertEqual([(d["product"]["name"], d["reason"], d["saving_pct"]) for d in res],
                         [("Mol go'shti", "cheaper", 30), ("Paxta yog'i", "promo", 25)])
        self.assertEqual(res[0]["offer"]["location"]["name"], "Mega do'kon")
        self.assertEqual(res[0]["offer"]["change"]["pct"], -30)
        self.assertEqual(res[1]["offer"]["link"], "https://shop.example/oil")
        self.assertEqual(self.api.get("/api/deals/?reason=promo").json()["results"][0]["product"]["name"],
                         "Paxta yog'i")
        self.assertEqual(self.api.get("/api/deals/?reason=nope").status_code, 400)

    def test_basket_totals(self):
        body = {"items": [{"product": self.meat.pk, "quantity": 2}, {"product": self.oil.pk, "quantity": 3}]}
        r = self.api.post("/api/basket/compare/", body, format="json").json()
        stores = [(s["location"]["name"], D(s["total"]), s["complete"]) for s in r["stores"]]
        self.assertEqual(stores, [("Mega do'kon", D("167000"), True), ("Chorsu bozori", D("222000"), True),
                                  ("Yangi bozor", D("200000"), False)])
        self.assertEqual((D(r["split_total"]), D(r["split_saving"])), (D("164000"), D("3000")))
        self.assertEqual(r["products"][str(self.oil.pk)]["base_unit"], "l")

    def test_basket_rejects_garbage(self):
        self.assertEqual(self.api.post("/api/basket/compare/", {"items": []}, format="json").status_code, 400)
        self.assertEqual(self.api.post("/api/basket/compare/", {"items": [{"product": 999999}]},
                                       format="json").status_code, 400)


class TrendApiTests(MarketBase):
    def test_daily_points(self):
        res = self.api.get(f"/api/products/{self.meat.pk}/trend/?days=30").json()
        pts = res["points"]
        self.assertEqual([p["date"] for p in pts], sorted(p["date"] for p in pts))
        self.assertEqual(sum(p["count"] for p in pts), 5)
        self.assertEqual((D(pts[0]["median_price"]), pts[0]["count"]), (D("90000"), 1))    # Chorsu, 5 days ago
        self.assertEqual(D(pts[1]["median_price"]), D("100000"))                          # Mega, 4 days ago
        self.assertEqual(res["source"], "live")


class VisibilityTests(MarketBase):
    def _set_status(self, status):
        PriceReport.objects.filter(product=self.eggs).update(status=status)

    def _eggs(self):
        return self.api.get(f"/api/products/{self.eggs.pk}/cheapest/?days=30").json()["results"]

    def test_pending_and_confirmed_are_shown(self):
        for status in ("pending", "confirmed"):
            self._set_status(status)
            self.assertEqual(len(self._eggs()), 1, status)

    def test_rejected_and_flagged_are_hidden(self):
        for status in ("rejected", "flagged"):
            self._set_status(status)
            self.assertEqual(self._eggs(), [], status)

    def test_inactive_place_and_product_are_hidden(self):
        Place.objects.filter(pk=self.a.pk).update(is_active=False)
        self.assertEqual(self._eggs(), [])
        Place.objects.filter(pk=self.a.pk).update(is_active=True)
        Product.objects.filter(pk=self.eggs.pk).update(is_active=False)
        self.assertEqual(self.api.get(f"/api/products/{self.eggs.pk}/").status_code, 404)


class PagesTests(MarketBase):
    def test_home_lists_categories_with_counts(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Go&#x27;sht", html)
        self.assertIn("3 ta mahsulot", html)

    def test_product_page_shows_offers_best_price_and_change(self):
        html = self.client.get(f"/product/{self.meat.pk}/").content.decode()
        self.assertIn("Mega do", html)
        self.assertIn("70 000", html)
        self.assertIn("▼", html)
        self.assertIn("30%", html)
        self.assertIn("Eng arzon", html)
        self.assertIn("Chorsu bozori", html)

    def test_unknown_product_and_category_are_404(self):
        self.assertEqual(self.client.get("/product/999999/").status_code, 404)
        self.assertEqual(self.client.get("/category/yoq/").status_code, 404)

    def test_category_page_lists_products(self):
        html = self.client.get("/category/gosht/").content.decode()
        for name in ("Mol go", "Paxta yog", "Tuxum"):
            self.assertIn(name, html)

    def test_add_form_is_shown_to_logged_in_users_only(self):
        self.assertNotContains(self.client.get("/"), 'id="add-form"')
        self.assertContains(self.client.get("/"), "tizimga kiring")
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/"), 'id="add-form"')

    def test_cart_reads_the_basket_from_the_api(self):
        self.assertContains(self.client.get("/cart/"), '"/api/basket/compare/"')

    def test_favicon_ico_redirects_to_the_svg(self):
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].endswith("/static/img/favicon.svg"))


class AccountPagesTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        from django.contrib.auth import get_user_model
        resp = self.client.post("/signup/", {"username": "yangi_user", "password1": "Bozor2026!narx",
                                             "password2": "Bozor2026!narx", "next": "/"})
        self.assertRedirects(resp, "/", fetch_redirect_response=False)
        user = get_user_model().objects.get(username="yangi_user")
        self.assertTrue(user.userprofile)                              # reputation profile created by the signal
        self.assertContains(self.client.get("/"), 'id="add-form"')     # new users can add prices right away

    def test_signup_blocks_open_redirects(self):
        resp = self.client.post("/signup/", {"username": "u2", "password1": "Bozor2026!narx",
                                             "password2": "Bozor2026!narx", "next": "https://evil.example/"})
        self.assertRedirects(resp, "/", fetch_redirect_response=False)

    def test_password_mismatch_shows_error(self):
        resp = self.client.post("/signup/", {"username": "u3", "password1": "Bozor2026!narx",
                                             "password2": "boshqa"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "error")

    def test_login_and_signup_pages(self):
        self.assertEqual(self.client.get("/login/").status_code, 200)
        self.assertEqual(self.client.get("/signup/").status_code, 200)

    def test_settings_password_change_and_confirm_need_login(self):
        for url in ("/settings/", "/settings/password/", "/tasdiqlash/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login/", r["Location"])


class ContentTests(MarketBase):
    """Product text and images used on the product page."""

    def setUp(self):
        Product.objects.filter(pk=self.meat.pk).update(description="Yangi go'sht.", usage="Qovurish uchun.",
                                                       image="products/mol.jpg")
        Category.objects.filter(slug="gosht").update(image="categories/gosht.png")

    def test_api_and_product_page_show_the_content(self):
        data = self.api.get(f"/api/products/{self.meat.pk}/").json()
        self.assertEqual((data["description"], data["usage"]), ("Yangi go'sht.", "Qovurish uchun."))
        self.assertTrue(data["image"].endswith("products/mol.jpg"))
        html = self.client.get(f"/product/{self.meat.pk}/").content.decode()
        self.assertIn("Yangi go&#x27;sht.", html)
        self.assertIn("Qovurish uchun.", html)
        self.assertIn("products/mol.jpg", html)

    def test_category_image_is_served(self):
        self.assertTrue(self.api.get("/api/categories/").json()[0]["image"].endswith("categories/gosht.png"))


class AlertsTests(MarketBase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.voter)

    def post(self, **over):
        body = {"product": self.meat.pk, "target_price": 80000}
        body.update(over)
        return self.client.post("/api/alerts/", body, format="json")

    def test_requires_login(self):
        self.assertIn(APIClient().get("/api/alerts/").status_code, (401, 403))

    def test_create_list_update_delete_own_alert(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.json())
        body = r.json()
        self.assertEqual((body["product_name"], body["base_unit"], body["is_reached"]), ("Mol go'shti", "kg", True))
        self.assertEqual(D(body["current_best"]), D("70000"))
        self.assertEqual(len(self.client.get("/api/alerts/").json()), 1)
        self.assertEqual(self.client.patch(f"/api/alerts/{body['id']}/", {"target_price": 50000},
                                           format="json").json()["is_reached"], False)
        self.assertEqual(self.client.delete(f"/api/alerts/{body['id']}/").status_code, 204)

    def test_one_alert_per_product_and_positive_target(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.post(product=self.eggs.pk, target_price=0).status_code, 400)

    def test_cannot_see_or_delete_others_alerts(self):
        mine = self.post().json()["id"]
        other = APIClient()
        other.force_authenticate(self.user)
        self.assertEqual(other.get("/api/alerts/").json(), [])
        self.assertEqual(other.delete(f"/api/alerts/{mine}/").status_code, 404)

    def test_command_fires_once_then_rearms_after_a_price_rise(self):
        self.post(target_price=60000)
        PriceReport.objects.create(product=self.meat, place=self.a, user=self.user, price=55000, quantity=1,
                                   unit="kg", status="confirmed")
        call_command("check_alerts", stdout=StringIO())
        alert = PriceAlert.objects.get()
        self.assertEqual(alert.last_notified_price, Decimal("55000.00"))
        first = alert.triggered_at
        call_command("check_alerts", stdout=StringIO())
        alert.refresh_from_db()
        self.assertEqual(alert.triggered_at, first)                         # not re-sent for the same price
        PriceReport.objects.filter(price=55000).update(status="rejected")   # the cheap price disappears
        call_command("check_alerts", stdout=StringIO())
        alert.refresh_from_db()
        self.assertIsNone(alert.last_notified_price)                        # re-armed
