"""v2 read API: same answers as the legacy /api/ for the same data, plus the new rules (pending visible)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from django.test import TestCase

from apps.catalog.models import Product, ProductAlias
from apps.reports.legacy import import_legacy
from apps.reports.models import PriceReport

from prices import models as legacy

User = get_user_model()


class ParityBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        legacy.Product.objects.all().delete()
        legacy.Category.objects.all().delete()
        cls.user = User.objects.create_user("seller", password="pw")
        cls.voter = User.objects.create_user("voter", password="pw")
        cat = legacy.Category.objects.create(name="Go'sht", slug="gosht")
        cls.meat = legacy.Product.objects.create(name="Mol go'shti", category=cat, base_unit="kg")
        cls.oil = legacy.Product.objects.create(name="Paxta yog'i", category=cat, base_unit="l")
        cls.eggs = legacy.Product.objects.create(name="Tuxum", category=cat, base_unit="piece")
        region = legacy.Region.objects.create(name="Namangan")
        d = legacy.District.objects.create(name="Markaz", region=region)
        cls.a = legacy.Location.objects.create(name="Chorsu bozori", type="bazaar", district=d, lat="41.000000", lng="71.670000")
        cls.b = legacy.Location.objects.create(name="Mega do'kon", type="shop", district=d, website="https://mega.example")
        cls.c = legacy.Location.objects.create(name="Yangi bozor", type="bazaar", district=d)
        now = timezone.now()

        def e(product, loc, price, qty, unit, days=0, hours=0, **kw):
            return legacy.PriceEntry.objects.create(
                product=product, location=loc, user=cls.user, price=price, quantity=qty, unit=unit,
                created_at=now - timedelta(days=days, hours=hours), **kw)

        e(cls.meat, cls.a, 90000, 1, "kg", days=5)
        e(cls.meat, cls.a, 99000, 1, "kg", hours=2)               # up 10% at the bazaar
        e(cls.meat, cls.b, 100000, 1, "kg", days=4)
        e(cls.meat, cls.b, 70000, 1, "kg", hours=3)               # down 30%, a "cheaper" deal
        e(cls.meat, cls.c, 50000, 500, "g", hours=1)              # 100 000 per kg, grams normalised
        e(cls.oil, cls.a, 16000, 2, "l", hours=4)
        e(cls.oil, cls.b, 9000, 1, "l", hours=5, is_promo=True, old_price=12000, source_url="https://shop.example/oil")
        e(cls.eggs, cls.a, 30000, 30, "piece", hours=6)
        import_legacy()
        cls.api = APIClient()

    def both(self, legacy_path, v2_path):
        return self.api.get("/api/" + legacy_path).json(), self.api.get("/api/v2/" + v2_path).json()

    def v2_product(self, name):
        return Product.objects.get(name=name)

    def legacy_product(self, name):
        return legacy.Product.objects.get(name=name)


class CatalogParityTests(ParityBase):
    def test_products_list_same_names_and_units(self):
        old, new = self.both("products/?page_size=50", "products/?page_size=50")
        self.assertEqual([(p["name"], p["base_unit"], p["category_name"]) for p in old["results"]],
                         [(p["name"], p["base_unit"], p["category_name"]) for p in new["results"]])
        self.assertEqual(set(new["results"][0]), set(old["results"][0]))  # same keys

    def test_search_ignores_case_and_apostrophes_and_finds_typos(self):
        for q in ("mol go'sht", "MOLGOSHT", "mol goshtt"):
            names = [p["name"] for p in self.api.get("/api/v2/products/", {"search": q}).json()["results"]]
            self.assertEqual(names, ["Mol go'shti"], q)

    def test_search_finds_aliases(self):
        ProductAlias.objects.create(product=self.v2_product("Mol go'shti"), alias="govyadina")
        names = [p["name"] for p in self.api.get("/api/v2/products/", {"search": "govyadina"}).json()["results"]]
        self.assertEqual(names, ["Mol go'shti"])

    def test_categories_and_districts_and_locations_shapes(self):
        old, new = self.both("categories/", "categories/")
        self.assertEqual(set(old[0]), set(new[0]))
        self.assertEqual(new[0]["product_count"], old[0]["product_count"])
        old, new = self.both("districts/", "districts/")
        self.assertEqual(set(old[0]), set(new[0]))
        old, new = self.both("locations/?page_size=50", "locations/?page_size=50")
        self.assertEqual(set(old["results"][0]), set(new["results"][0]))
        self.assertEqual(sorted(p["name"] for p in old["results"]), sorted(p["name"] for p in new["results"]))


class CheapestParityTests(ParityBase):
    def _compare(self, name, query=""):
        old = self.api.get(f"/api/products/{self.legacy_product(name).pk}/cheapest/{query}").json()
        new = self.api.get(f"/api/v2/products/{self.v2_product(name).pk}/cheapest/{query}").json()
        return old["results"], new["results"]

    def test_same_order_prices_units_links_and_changes(self):
        old, new = self._compare("Mol go'shti", "?days=30")
        self.assertEqual(len(old), 3)
        pick = lambda r: (r["location"]["name"], Decimal(str(r["normalized_price"])), r["unit"], r["base_unit"],
                          r["link_kind"], r["is_promo"], r["change"] and (r["change"]["dir"], r["change"]["pct"]))
        self.assertEqual([pick(r) for r in old], [pick(r) for r in new])
        self.assertEqual(set(old[0]), set(new[0]))

    def test_promo_and_source_link_survive(self):
        old, new = self._compare("Paxta yog'i")
        promo_old = next(r for r in old if r["is_promo"])
        promo_new = next(r for r in new if r["is_promo"])
        self.assertEqual(promo_old["link"], promo_new["link"])
        self.assertEqual(promo_new["link"], "https://shop.example/oil")
        self.assertEqual(int(promo_new["old_price"]), 12000)

    def test_unit_codes_use_the_legacy_spelling(self):
        _, new = self._compare("Paxta yog'i")
        self.assertEqual({r["unit"] for r in new}, {"l"})
        self.assertEqual(new[0]["base_unit"], "l")

    def test_district_filter_is_the_city(self):
        city = self.api.get("/api/v2/districts/").json()[0]["id"]
        res = self.api.get(f"/api/v2/products/{self.v2_product('Mol go' + chr(39) + 'shti').pk}/cheapest/?district={city}").json()
        self.assertEqual(len(res["results"]), 3)
        none = self.api.get(f"/api/v2/products/{self.v2_product('Mol go' + chr(39) + 'shti').pk}/cheapest/?district=999999").json()
        self.assertEqual(none["results"], [])

    def test_bad_params_are_rejected_like_before(self):
        pk = self.v2_product("Tuxum").pk
        self.assertEqual(self.api.get(f"/api/v2/products/{pk}/cheapest/?days=0").status_code, 400)
        self.assertEqual(self.api.get(f"/api/v2/products/{pk}/cheapest/?sort=distance").status_code, 400)


class DealsAndBasketParityTests(ParityBase):
    def test_deals_match(self):
        old, new = self.both("deals/?limit=20", "deals/?limit=20")
        pick = lambda d: (d["product"]["name"], d["reason"], d["saving_pct"], d["offer"]["location"]["name"],
                          Decimal(str(d["offer"]["normalized_price"])), d["offer"]["link_kind"],
                          d["offer"]["change"] and d["offer"]["change"]["pct"])
        self.assertEqual([pick(d) for d in old["results"]], [pick(d) for d in new["results"]])
        self.assertTrue(new["results"])
        self.assertEqual(set(old["results"][0]["offer"]), set(new["results"][0]["offer"]))

    def test_basket_totals_match(self):
        def body(model, names):
            return {"items": [{"product": model.objects.get(name=n).pk, "quantity": q} for n, q in names]}
        names = [("Mol go'shti", 2), ("Paxta yog'i", 3)]
        old = self.api.post("/api/basket/compare/", body(legacy.Product, names), format="json").json()
        new = self.api.post("/api/v2/basket/compare/", body(Product, names), format="json").json()
        pick = lambda r: ([(s["location"]["name"], Decimal(str(s["total"])), s["complete"]) for s in r["stores"]],
                          Decimal(str(r["split_total"])), r["split_saving"] and Decimal(str(r["split_saving"])))
        self.assertEqual(pick(old), pick(new))
        self.assertEqual(set(old), set(new))

    def test_basket_rejects_garbage(self):
        self.assertEqual(self.api.post("/api/v2/basket/compare/", {"items": []}, format="json").status_code, 400)
        self.assertEqual(self.api.post("/api/v2/basket/compare/", {"items": [{"product": 999999}]},
                                       format="json").status_code, 400)


class TrendParityTests(ParityBase):
    def test_daily_points_match(self):
        old = self.api.get(f"/api/products/{self.legacy_product('Mol go' + chr(39) + 'shti').pk}/trend/?days=30").json()
        new = self.api.get(f"/api/v2/products/{self.v2_product('Mol go' + chr(39) + 'shti').pk}/trend/?days=30").json()
        pick = lambda p: (p["date"], Decimal(str(p["median_price"])), Decimal(str(p["min_price"])),
                          Decimal(str(p["max_price"])), p["count"])
        self.assertEqual([pick(p) for p in old["points"]], [pick(p) for p in new["points"]])
        self.assertGreaterEqual(len(new["points"]), 2)
        self.assertTrue(new["points"][-1]["live"])


class VisibilityTests(ParityBase):
    def _set_status(self, status):
        report = PriceReport.objects.filter(product__name="Tuxum").get()
        PriceReport.objects.filter(pk=report.pk).update(status=status)

    def _eggs(self):
        pk = self.v2_product("Tuxum").pk
        return self.api.get(f"/api/v2/products/{pk}/cheapest/?days=30").json()["results"]

    def test_pending_and_confirmed_are_shown(self):
        self._set_status("pending")
        self.assertEqual(len(self._eggs()), 1)
        self._set_status("confirmed")
        self.assertEqual(len(self._eggs()), 1)

    def test_rejected_and_flagged_are_hidden(self):
        for status in ("rejected", "flagged"):
            self._set_status(status)
            self.assertEqual(self._eggs(), [], status)

    def test_inactive_place_and_product_are_hidden(self):
        place = PriceReport.objects.get(product__name="Tuxum").place
        place.is_active = False
        place.save()
        self.assertEqual(self._eggs(), [])
        place.is_active = True
        place.save()
        Product.objects.filter(name="Tuxum").update(is_active=False)
        self.assertEqual(self.api.get(f"/api/v2/products/{self.v2_product('Tuxum').pk}/").status_code, 404)


from django.test import override_settings
from apps.catalog.models import Category


class PagesUnderFlagTests(ParityBase):
    """Same templates, rendered from the new models when USE_NEW_API is on."""

    def test_flag_off_by_default_and_pages_point_js_at_legacy_api(self):
        html = self.client.get("/").content.decode()
        self.assertIn('data-api="/api/"', html)

    @override_settings(USE_NEW_API=True)
    def test_home_uses_new_categories_and_api_base(self):
        html = self.client.get("/").content.decode()
        self.assertIn('data-api="/api/v2/"', html)
        self.assertIn("Go&#x27;sht", html)
        self.assertIn("3 ta mahsulot", html)

    @override_settings(USE_NEW_API=True)
    def test_add_form_is_shown_to_logged_in_users(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/"), 'id="add-form"')

    @override_settings(USE_NEW_API=True)
    def test_product_page_shows_offers_best_price_and_change(self):
        pk = self.v2_product("Mol go'shti").pk
        html = self.client.get(f"/product/{pk}/").content.decode()
        self.assertIn("Mega do", html)           # cheapest place first
        self.assertIn("70 000", html)
        self.assertIn("▼", html)                # 100 000 -> 70 000
        self.assertIn("30%", html)
        self.assertIn("Eng arzon", html)
        self.assertIn("Chorsu bozori", html)

    @override_settings(USE_NEW_API=True)
    def test_inactive_or_unknown_product_is_404(self):
        self.assertEqual(self.client.get("/product/999999/").status_code, 404)

    @override_settings(USE_NEW_API=True)
    def test_category_page_lists_products_cheapest_first(self):
        cat = Category.objects.get(slug="gosht")
        html = self.client.get(f"/category/{cat.slug}/").content.decode()
        for name in ("Mol go", "Paxta yog", "Tuxum"):
            self.assertIn(name, html)
        self.assertEqual(self.client.get("/category/yoq/").status_code, 404)

    @override_settings(USE_NEW_API=True)
    def test_cart_reads_basket_from_the_active_api(self):
        html = self.client.get("/cart/").content.decode()
        self.assertIn('NK.API_READ + "basket/compare/"', html)
        self.assertIn('data-api="/api/v2/"', html)


class FaviconTests(TestCase):
    def test_favicon_ico_redirects_to_the_svg(self):
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].endswith("/static/img/favicon.svg"))


class AddFormPlacesTests(ParityBase):
    """The add-price form lists every place; the API paginates at 20 unless asked for more."""

    def test_home_asks_for_the_full_place_list(self):
        self.assertContains(self.client.get("/"), 'api("locations/?page_size=200")')

    def test_both_apis_return_all_places_with_page_size(self):
        from apps.catalog.models import City, Place
        city = City.objects.get()
        for i in range(25):
            Place.objects.create(name=f"Joy {i}", type="shop", city=city)
        new = self.api.get("/api/v2/locations/?page_size=200").json()
        self.assertEqual(new["count"], 28)
        self.assertEqual(len(new["results"]), 28)
        self.assertEqual(len(self.api.get("/api/v2/locations/").json()["results"]), 20)


class ProductIdMapTests(ParityBase):
    def test_maps_both_ways_by_name(self):
        m = self.api.get("/api/v2/product-id-map/").json()
        old, new = self.legacy_product("Mol go'shti").pk, self.v2_product("Mol go'shti").pk
        self.assertEqual(m["to_v2"][str(old)], new)
        self.assertEqual(m["to_legacy"][str(new)], old)

    def test_products_missing_on_one_side_are_left_out(self):
        legacy.Product.objects.create(name="Faqat eski", category=legacy.Category.objects.get(slug="gosht"),
                                      base_unit="kg")
        m = self.api.get("/api/v2/product-id-map/").json()
        only_old = legacy.Product.objects.get(name="Faqat eski").pk
        self.assertNotIn(str(only_old), m["to_v2"])

    def test_pages_include_the_remap_code(self):
        self.assertIn("remapIds", open("static/js/app.js", encoding="utf-8").read())


class AlertsOnNewPricesTests(ParityBase):
    """Price alerts belong to the legacy product but must see new prices once the flag is on."""

    def setUp(self):
        from apps.catalog.models import Place
        self.alert = legacy.PriceAlert.objects.create(user=self.voter, product=self.legacy_product("Mol go'shti"),
                                                       target_price=60000)
        # a cheaper price that exists ONLY in the new system
        PriceReport.objects.create(product=self.v2_product("Mol go'shti"), place=Place.objects.get(name="Chorsu bozori"),
                                   user=self.user, price=55000, quantity=1, unit="kg", status="confirmed")

    def test_flag_off_alerts_see_only_legacy_prices(self):
        from prices.services import best_current_price
        self.assertEqual(best_current_price(self.alert.product), Decimal("70000.00"))

    @override_settings(USE_NEW_API=True)
    def test_flag_on_alerts_see_new_prices(self):
        from prices.services import best_current_price
        self.assertEqual(best_current_price(self.alert.product), Decimal("55000.00"))

    @override_settings(USE_NEW_API=True)
    def test_command_fires_on_a_new_price_and_api_reports_it(self):
        from io import StringIO
        from django.core.management import call_command
        call_command("check_price_alerts", stdout=StringIO())
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.last_notified_price, Decimal("55000.00"))
        c = APIClient()
        c.force_authenticate(self.voter)
        row = c.get("/api/alerts/").json()[0]
        self.assertTrue(row["is_reached"])

    @override_settings(USE_NEW_API=True)
    def test_unmatched_product_gives_no_price(self):
        from prices.services import best_current_price
        odd = legacy.Product.objects.create(name="Faqat eski 2", category=legacy.Category.objects.get(slug="gosht"),
                                            base_unit="kg")
        self.assertIsNone(best_current_price(odd))


class ContentCarryOverTests(ParityBase):
    """Product text and images used on the product page survive the move."""

    def test_existing_product_gets_blank_fields_filled_but_never_overwritten(self):
        legacy.Product.objects.filter(name="Mol go'shti").update(description="Yangi go'sht.", usage="Qovurish uchun.",
                                                                 image="products/mol.jpg")
        stats = import_legacy()
        p = Product.objects.get(name="Mol go'shti")
        self.assertEqual((p.description, p.usage, p.image.name), ("Yangi go'sht.", "Qovurish uchun.", "products/mol.jpg"))
        self.assertEqual(stats["products_enriched"], 1)
        legacy.Product.objects.filter(name="Mol go'shti").update(description="Boshqa matn.")
        import_legacy()
        self.assertEqual(Product.objects.get(name="Mol go'shti").description, "Yangi go'sht.")  # not overwritten

    def test_new_product_is_created_with_its_content(self):
        cat = legacy.Category.objects.get(slug="gosht")
        legacy.Product.objects.create(name="Qo'y go'shti", category=cat, base_unit="kg", description="Mayin.",
                                      usage="Palov uchun.", image="products/qoy.jpg")
        import_legacy()
        p = Product.objects.get(name="Qo'y go'shti")
        self.assertEqual((p.description, p.usage, p.image.name), ("Mayin.", "Palov uchun.", "products/qoy.jpg"))

    def test_category_image_is_copied(self):
        legacy.Category.objects.filter(slug="gosht").update(image="categories/gosht.png")
        import_legacy()
        from apps.catalog.models import Category
        self.assertEqual(Category.objects.get(slug="gosht").image.name, "categories/gosht.png")

    def test_v2_api_and_product_page_show_the_content(self):
        legacy.Product.objects.filter(name="Mol go'shti").update(description="Yangi go'sht.", usage="Qovurish uchun.",
                                                                 image="products/mol.jpg")
        import_legacy()
        pk = self.v2_product("Mol go'shti").pk
        data = self.api.get(f"/api/v2/products/{pk}/").json()
        self.assertEqual((data["description"], data["usage"]), ("Yangi go'sht.", "Qovurish uchun."))
        self.assertTrue(data["image"].endswith("products/mol.jpg"))
        with override_settings(USE_NEW_API=True):
            html = self.client.get(f"/product/{pk}/").content.decode()
        self.assertIn("Yangi go&#x27;sht.", html)
        self.assertIn("Qovurish uchun.", html)
        self.assertIn("products/mol.jpg", html)


class NewAlertsTests(ParityBase):
    def setUp(self):
        from apps.catalog.models import Place
        self.meat_new = self.v2_product("Mol go'shti")
        self.client = APIClient()
        self.client.force_authenticate(self.voter)
        self.place = Place.objects.get(name="Chorsu bozori")

    def post(self, **over):
        body = {"product": self.meat_new.pk, "target_price": 80000}
        body.update(over)
        return self.client.post("/api/v2/alerts/", body, format="json")

    def test_requires_login(self):
        self.assertIn(APIClient().get("/api/v2/alerts/").status_code, (401, 403))

    def test_create_list_update_delete_own_alert(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.json())
        body = r.json()
        self.assertEqual((body["product_name"], body["base_unit"], body["is_reached"]), ("Mol go'shti", "kg", True))
        self.assertEqual(Decimal(str(body["current_best"])), Decimal("70000.00"))
        self.assertEqual(len(self.client.get("/api/v2/alerts/").json()), 1)
        self.assertEqual(self.client.patch(f"/api/v2/alerts/{body['id']}/", {"target_price": 50000}, format="json")
                         .json()["is_reached"], False)
        self.assertEqual(self.client.delete(f"/api/v2/alerts/{body['id']}/").status_code, 204)

    def test_one_alert_per_product_and_positive_target(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.post(product=self.v2_product("Tuxum").pk, target_price=0).status_code, 400)

    def test_cannot_see_or_delete_others_alerts(self):
        mine = self.post().json()["id"]
        other = APIClient()
        other.force_authenticate(self.user)
        self.assertEqual(other.get("/api/v2/alerts/").json(), [])
        self.assertEqual(other.delete(f"/api/v2/alerts/{mine}/").status_code, 404)

    def test_command_fires_once_then_rearms_after_a_price_rise(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.market.models import PriceAlert
        self.post(target_price=60000)
        PriceReport.objects.create(product=self.meat_new, place=self.place, user=self.user, price=55000, quantity=1,
                                   unit="kg", status="confirmed")
        call_command("check_alerts", stdout=StringIO())
        alert = PriceAlert.objects.get()
        self.assertEqual(alert.last_notified_price, Decimal("55000.00"))
        first = alert.triggered_at
        call_command("check_alerts", stdout=StringIO())
        alert.refresh_from_db()
        self.assertEqual(alert.triggered_at, first)                    # not re-sent for the same price
        PriceReport.objects.filter(price=55000).update(status="rejected")   # cheap price disappears
        call_command("check_alerts", stdout=StringIO())
        alert.refresh_from_db()
        self.assertIsNone(alert.last_notified_price)                   # re-armed

    def test_legacy_alerts_are_imported_once(self):
        legacy.PriceAlert.objects.create(user=self.voter, product=self.legacy_product("Mol go'shti"), target_price=65000,
                                         is_active=False)
        stats = import_legacy()
        self.assertEqual(stats["alerts_created"], 1)
        from apps.market.models import PriceAlert
        a = PriceAlert.objects.get()
        self.assertEqual((a.user, a.product, a.target_price, a.is_active), (self.voter, self.meat_new, 65000, False))
        self.assertEqual(import_legacy()["alerts_existing"], 1)
        self.assertEqual(PriceAlert.objects.count(), 1)
