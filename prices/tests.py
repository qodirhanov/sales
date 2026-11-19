from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Category, DailyPriceStat, District, Location, PriceEntry, Product, Profile, Region

User = get_user_model()


class BaseData(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tester", password="pw")
        Product.objects.all().delete()  # products seeded by migration 0009 (PROTECT)
        Category.objects.all().delete()  # drop departments seeded by migration 0008; tests build their own
        cat = Category.objects.create(name="Go'sht", slug="gosht")
        cls.meat = Product.objects.create(name="Mol go'shti", category=cat, base_unit="kg")
        cls.oil = Product.objects.create(name="Paxta yog'i", category=cat, base_unit="l")
        region = Region.objects.create(name="Toshkent")
        cls.district = District.objects.create(name="Chilonzor", region=region)
        cls.loc_a = Location.objects.create(name="A bozori", type="bazaar", district=cls.district)
        cls.loc_b = Location.objects.create(name="B bozori", type="bazaar", district=cls.district)
        cls.loc_c = Location.objects.create(name="C shop", type="shop", district=cls.district)

    def make(self, product=None, location=None, price=100000, quantity=1, unit="kg", **kw):
        return PriceEntry.objects.create(
            product=product or self.meat, location=location or self.loc_a, user=self.user,
            price=price, quantity=quantity, unit=unit, **kw,
        )


class NormalizationTests(BaseData):
    def test_grams_converted_to_kg(self):
        e = self.make(price=30000, quantity=500, unit="g")
        self.assertEqual(e.normalized_price, Decimal("60000.00"))

    def test_ml_converted_to_l(self):
        e = self.make(product=self.oil, price=8000, quantity=500, unit="ml")
        self.assertEqual(e.normalized_price, Decimal("16000.00"))

    def test_incompatible_unit_rejected(self):
        with self.assertRaises(ValidationError):
            self.make(product=self.meat, price=10000, quantity=1, unit="l")
        with self.assertRaises(ValidationError):
            self.make(product=self.oil, price=10000, quantity=1, unit="g")
        self.assertEqual(PriceEntry.objects.count(), 0)


class OutlierTests(BaseData):
    def test_no_flag_with_fewer_than_three_samples(self):
        self.make(price=100000)
        self.make(price=100000)
        self.assertFalse(self.make(price=900000).is_flagged)

    def test_outlier_flagged(self):
        for _ in range(3):
            self.make(price=100000)
        self.assertTrue(self.make(price=160000).is_flagged)   # +60%
        self.assertTrue(self.make(price=40000).is_flagged)    # -60%
        self.assertFalse(self.make(price=140000).is_flagged)  # +40%

    def test_old_entries_ignored(self):
        old = timezone.now() - timedelta(days=40)
        for _ in range(3):
            self.make(price=100000, created_at=old)
        self.assertFalse(self.make(price=900000).is_flagged)


class CheapestEndpointTests(BaseData):
    def test_sorted_ascending_latest_per_location_excluding_flagged(self):
        now = timezone.now()
        # Location A: older cheap price, then newer expensive -> latest (120000) counts.
        self.make(location=self.loc_a, price=50000, created_at=now - timedelta(days=2))
        self.make(location=self.loc_a, price=120000, created_at=now - timedelta(days=1))
        self.make(location=self.loc_b, price=90000, created_at=now - timedelta(hours=3))
        # Location C: price in grams, 100000/kg equivalent
        self.make(location=self.loc_c, price=50000, quantity=500, unit="g")
        # Flagged entry must be ignored
        self.make(location=self.loc_b, price=1000, is_flagged=True)
        # Outside window
        self.make(location=self.loc_c, price=10000, created_at=now - timedelta(days=30))

        r = APIClient().get(f"/api/products/{self.meat.id}/cheapest/?days=7&district={self.district.id}")
        self.assertEqual(r.status_code, 200)
        names = [x["location"]["name"] for x in r.data["results"]]
        prices = [Decimal(str(x["normalized_price"])) for x in r.data["results"]]
        self.assertEqual(names, ["B bozori", "C shop", "A bozori"])
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(prices, [Decimal("90000"), Decimal("100000"), Decimal("120000")])
        self.assertIn("created_at", r.data["results"][0])


class PriceApiTests(BaseData):
    def payload(self, **kw):
        d = {"product": self.meat.id, "location": self.loc_a.id, "price": "95000",
             "quantity": "1", "unit": "kg"}
        d.update(kw)
        return d

    def test_requires_auth(self):
        self.assertIn(APIClient().post("/api/prices/", self.payload()).status_code, (401, 403))

    def test_create_sets_user_and_rejects_bad_unit(self):
        c = APIClient()
        c.force_authenticate(self.user)
        r = c.post("/api/prices/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(PriceEntry.objects.get().user, self.user)
        r = c.post("/api/prices/", self.payload(unit="ml"), format="json")
        self.assertEqual(r.status_code, 400)

    def test_any_logged_in_user_can_create_price(self):
        newcomer = User.objects.create_user("newcomer", password="pw")
        c = APIClient()
        c.force_authenticate(newcomer)
        r = c.post("/api/prices/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(PriceEntry.objects.get().user, newcomer)

    def test_anonymous_cannot_create_price_but_can_read(self):
        c = APIClient()
        self.assertIn(c.post("/api/prices/", self.payload(), format="json").status_code, (401, 403))
        self.assertEqual(PriceEntry.objects.count(), 0)
        self.assertEqual(c.get("/api/prices/").status_code, 200)

    def test_seller_can_create_price(self):
        c = APIClient()
        c.force_authenticate(self.user)
        self.assertEqual(c.post("/api/prices/", self.payload(), format="json").status_code, 201)

    def test_user_without_profile_can_still_create_price(self):
        user = User.objects.create_user("noprofile", password="pw")
        user.profile.delete()
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        self.assertEqual(c.post("/api/prices/", self.payload(), format="json").status_code, 201)

    def test_list_excludes_flagged(self):
        self.make()
        self.make(is_flagged=True)
        r = APIClient().get("/api/prices/")
        self.assertEqual(r.data["count"], 1)


class AggregateCommandTests(BaseData):
    def test_aggregate_excludes_flagged_and_computes_median(self):
        day = timezone.now() - timedelta(days=1)
        for p in (100000, 110000, 120000):
            self.make(price=p, created_at=day)
        self.make(price=1000, created_at=day, is_flagged=True)
        call_command("aggregate_daily_prices", date=timezone.localtime(day).date().isoformat())
        s = DailyPriceStat.objects.get()
        self.assertEqual((s.min_price, s.median_price, s.max_price, s.count),
                         (Decimal("100000"), Decimal("110000"), Decimal("120000"), 3))


class TrendEndpointTests(BaseData):
    def test_today_shown_live_next_to_aggregated_days(self):
        yesterday_entry = self.make(price=100000)
        PriceEntry.objects.filter(pk=yesterday_entry.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
        call_command("aggregate_daily_prices", date=yesterday.isoformat())
        self.make(location=self.loc_a, price=110000)
        self.make(location=self.loc_b, price=130000)

        resp = APIClient().get(f"/api/products/{self.meat.id}/trend/?days=7")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["source"], "mixed")
        points = resp.data["points"]
        self.assertEqual(len(points), 2)
        self.assertFalse(points[0]["live"])
        self.assertEqual(points[0]["median_price"], Decimal("100000"))
        self.assertTrue(points[1]["live"])
        self.assertEqual(points[1]["median_price"], Decimal("120000"))
        self.assertEqual(points[1]["count"], 2)


class WebPageTests(BaseData):
    def test_home_and_login_pages_render(self):
        client = APIClient()
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "Narx kuzatuvchi")
        self.assertContains(home, "tizimga kiring")
        self.assertIn("csrftoken", home.cookies)
        self.assertEqual(client.get("/login/").status_code, 200)

    def test_logged_in_user_sees_add_form(self):
        client = APIClient()
        client.force_login(self.user)
        self.assertContains(client.get("/"), 'id="add-form"')

    def test_every_logged_in_user_sees_add_form(self):
        newcomer = User.objects.create_user("newcomer2", password="pw")
        client = APIClient()
        client.force_login(newcomer)
        self.assertContains(client.get("/"), 'id="add-form"')


class SettingsPageTests(BaseData):
    def test_requires_login(self):
        r = self.client.get("/settings/")
        self.assertRedirects(r, "/login/?next=/settings/", fetch_redirect_response=False)
        self.assertEqual(self.client.post("/settings/", {"action": "save_profile"}).status_code, 302)

    def test_role_switch_actions_are_gone(self):
        user = User.objects.create_user("b3", password="pw")
        self.client.force_login(user)
        r = self.client.post("/settings/", {"action": "become_seller", "shop_name": "X"})
        self.assertRedirects(r, "/settings/", fetch_redirect_response=False)
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.shop_name, "")  # unknown action changes nothing

    def test_save_profile_validates_length(self):
        self.client.force_login(self.user)
        self.client.post("/settings/", {"action": "save_profile", "shop_name": "X" * 121, "phone": "1"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.shop_name, "")
        self.client.post("/settings/", {"action": "save_profile", "shop_name": "Bozor", "phone": "+998901234567"})
        self.user.profile.refresh_from_db()
        self.assertEqual((self.user.profile.shop_name, self.user.profile.phone), ("Bozor", "+998901234567"))

    def test_context_has_entries(self):
        for _ in range(12):
            self.make()
        self.client.force_login(self.user)
        r = self.client.get("/settings/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["my_entries_count"], 12)
        self.assertEqual(len(r.context["recent_entries"]), 10)
        self.assertEqual(r.context["profile"], self.user.profile)


class SignupTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        resp = self.client.post("/signup/", {
            "username": "yangi_user", "password1": "Bozor2026!narx", "password2": "Bozor2026!narx",
            "next": "/",
        })
        self.assertRedirects(resp, "/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="yangi_user").exists())
        user = User.objects.get(username="yangi_user")
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertContains(self.client.get("/"), 'id="add-form"')  # new users can add prices right away

    def test_password_mismatch_shows_error(self):
        resp = self.client.post("/signup/", {
            "username": "u2", "password1": "Bozor2026!narx", "password2": "boshqa-parol-1",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="u2").exists())

    def test_open_redirect_blocked(self):
        resp = self.client.post("/signup/", {
            "username": "u3", "password1": "Bozor2026!narx", "password2": "Bozor2026!narx",
            "next": "https://evil.example/",
        })
        self.assertRedirects(resp, "/", fetch_redirect_response=False)


# ------------------------------------------------------------------ marketplace
class MarketplaceData(BaseData):
    def deals(self, **params):
        r = APIClient().get("/api/deals/", params)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["results"]


class OfferLinkTests(MarketplaceData):
    def test_priority_source_url_then_website_then_map(self):
        from .services import offer_link

        e = self.make(source_url="https://uzum.uz/p/1")
        self.loc_a.website = "https://shop.uz"
        self.assertEqual(offer_link(e), ("https://uzum.uz/p/1", "store"))
        e.source_url = ""
        self.assertEqual(offer_link(e), ("https://shop.uz", "store"))
        self.loc_a.website = ""
        self.loc_a.lat, self.loc_a.lng = Decimal("41.311100"), Decimal("69.279700")
        self.assertEqual(offer_link(e), ("https://www.google.com/maps?q=41.311100,69.279700", "map"))
        self.loc_a.lat = self.loc_a.lng = None
        self.loc_a.address = "Eski shahar"
        url, kind = offer_link(e)
        self.assertEqual(kind, "map")
        self.assertTrue(url.startswith("https://www.google.com/maps/search/?api=1&query="))
        self.assertIn("A%20bozori", url)

    def test_non_http_url_ignored(self):
        from .services import offer_link

        e = self.make(source_url="javascript:alert(1)")
        self.assertEqual(offer_link(e)[1], "map")

    def test_model_validator_rejects_ftp(self):
        e = PriceEntry(product=self.meat, location=self.loc_a, user=self.user, price=1, quantity=1,
                       unit="kg", source_url="ftp://x.uz/a")
        with self.assertRaises(ValidationError) as cm:
            e.full_clean(exclude=["normalized_price"])
        self.assertIn("source_url", cm.exception.message_dict)


class PriceSerializerTests(MarketplaceData):
    def post(self, **kw):
        d = {"product": self.meat.id, "location": self.loc_a.id, "price": "80000", "quantity": "1", "unit": "kg"}
        d.update(kw)
        c = APIClient()
        c.force_authenticate(self.user)
        return c.post("/api/prices/", d, format="json")

    def test_promo_ok_and_returned(self):
        r = self.post(is_promo=True, old_price="100000", source_url="https://uzum.uz/ru")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["is_promo"])
        self.assertEqual(r.data["source_url"], "https://uzum.uz/ru")

    def test_old_price_must_exceed_price(self):
        self.assertEqual(self.post(old_price="80000").status_code, 400)
        self.assertEqual(self.post(old_price="70000").status_code, 400)
        self.assertEqual(self.post(old_price="90000").status_code, 201)

    def test_promo_requires_old_price(self):
        self.assertEqual(self.post(is_promo=True).status_code, 400)

    def test_source_url_scheme(self):
        self.assertEqual(self.post(source_url="javascript:alert(1)").status_code, 400)
        self.assertEqual(self.post(source_url="ftp://a.uz/x").status_code, 400)
        self.assertEqual(self.post(source_url="http://a.uz/x").status_code, 201)


class DealsEndpointTests(MarketplaceData):
    def test_promo_deal(self):
        self.make(price=80000, old_price=100000, is_promo=True, source_url="https://uzum.uz/ru")
        res = self.deals(reason="promo")
        self.assertEqual(len(res), 1)
        d = res[0]
        self.assertEqual(d["reason"], "promo")
        self.assertEqual(d["saving_pct"], 20)
        self.assertEqual(d["offer"]["discount_pct"], 20)
        self.assertEqual(d["offer"]["link"], "https://uzum.uz/ru")
        self.assertEqual(d["offer"]["link_kind"], "store")
        self.assertEqual(d["product"]["id"], self.meat.id)
        self.assertEqual(d["offer"]["location"]["id"], self.loc_a.id)
        self.assertIsNone(d["product"]["image"])

    def test_promo_ignored_when_latest_entry_is_not_promo(self):
        now = timezone.now()
        self.make(price=80000, old_price=100000, is_promo=True, created_at=now - timedelta(days=1))
        self.make(price=100000, created_at=now)
        self.assertEqual(self.deals(reason="promo"), [])

    def test_cheaper_deal_uses_median_of_others(self):
        self.make(location=self.loc_a, price=100000)
        self.make(location=self.loc_b, price=100000)
        self.make(location=self.loc_c, price=80000)  # 20% below median(100000, 100000)
        res = self.deals(reason="cheaper")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["reason"], "cheaper")
        self.assertEqual(res[0]["saving_pct"], 20)
        self.assertEqual(res[0]["offer"]["location"]["id"], self.loc_c.id)

    def test_cheaper_needs_two_locations_and_ten_percent(self):
        self.make(location=self.loc_a, price=100000)
        self.assertEqual(self.deals(reason="cheaper"), [])  # single location
        self.make(location=self.loc_b, price=95000)  # only 5% lower
        self.assertEqual(self.deals(reason="cheaper"), [])
        self.make(location=self.loc_c, price=90000)  # ~7.7% below median(100000, 95000) -> no
        self.assertEqual(self.deals(reason="cheaper"), [])

    def test_promo_wins_over_cheaper_one_card_per_product(self):
        self.make(location=self.loc_a, price=100000)
        self.make(location=self.loc_b, price=70000, old_price=90000, is_promo=True)
        res = self.deals()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["reason"], "promo")

    def test_exclusions(self):
        self.make(location=self.loc_a, price=100000)
        self.make(location=self.loc_b, price=50000, is_flagged=True)
        old = self.make(location=self.loc_c, price=50000, is_flagged=False)
        PriceEntry.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        self.assertEqual(self.deals(), [])  # flagged + stale ignored

        self.make(location=self.loc_b, price=50000, is_flagged=False)
        self.assertEqual(len(self.deals()), 1)
        self.loc_b.is_active = False
        self.loc_b.save()
        self.assertEqual(self.deals(), [])  # inactive location
        self.loc_b.is_active = True
        self.loc_b.save()
        self.meat.is_active = False
        self.meat.save()
        self.assertEqual(self.deals(), [])  # inactive product

    def test_params_and_sorting(self):
        self.make(product=self.meat, price=90000, old_price=100000, is_promo=True)  # 10%
        self.make(product=self.oil, unit="l", price=6000, old_price=10000, is_promo=True)  # 40%
        res = self.deals()
        self.assertEqual([d["saving_pct"] for d in res], [40, 10])
        self.assertEqual(len(self.deals(limit=1)), 1)
        self.assertEqual(len(self.deals(category="yoq")), 0)
        self.assertEqual(len(self.deals(category="gosht")), 2)
        self.assertEqual(len(self.deals(district=self.district.id + 99)), 0)
        c = APIClient()
        self.assertEqual(c.get("/api/deals/?reason=bad").status_code, 400)
        self.assertEqual(c.get("/api/deals/?limit=49").status_code, 400)

    def test_latest_entry_per_location_is_used(self):
        now = timezone.now()
        self.make(location=self.loc_a, price=50000, created_at=now - timedelta(days=2))
        self.make(location=self.loc_a, price=100000, created_at=now)
        self.make(location=self.loc_b, price=100000)
        self.make(location=self.loc_c, price=100000)
        self.assertEqual(self.deals(), [])

    def test_cheapest_endpoint_has_link_fields(self):
        self.make(price=80000, old_price=100000, is_promo=True, source_url="https://uzum.uz/ru")
        r = APIClient().get(f"/api/products/{self.meat.id}/cheapest/").json()["results"][0]
        self.assertEqual(r["link"], "https://uzum.uz/ru")
        self.assertEqual(r["link_kind"], "store")
        self.assertTrue(r["is_promo"])
        self.assertEqual(Decimal(r["old_price"]), Decimal("100000"))
        self.assertIn("normalized_price", r)

    def test_category_and_product_serializers(self):
        cat = self.meat.category
        cat.emoji = "X"
        cat.save()
        c = APIClient()
        row = c.get("/api/categories/").json()[0]
        self.assertEqual(row["emoji"], "X")
        self.assertEqual(row["product_count"], 2)
        self.assertIsNone(row["image"])
        p = c.get(f"/api/products/{self.meat.id}/").json()
        self.assertEqual(p["category_name"], "Go'sht")
        self.assertIn("description", p)
        self.assertIn("usage", p)
        self.assertIsNone(p["image"])


class MarketplacePageTests(MarketplaceData):
    def test_index_has_categories_with_counts(self):
        self.oil.is_active = False
        self.oil.save()
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        cats = list(r.context["categories"])
        self.assertEqual([(c.slug, c.product_count) for c in cats], [("gosht", 1)])

    def test_product_detail(self):
        self.make(location=self.loc_a, price=100000)
        self.make(location=self.loc_b, price=80000, source_url="https://uzum.uz/ru")
        r = self.client.get(f"/product/{self.meat.id}/")
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(ctx["offer_count"], 2)
        self.assertEqual(ctx["unit_label"], "kg")
        offers = ctx["offers"]
        self.assertEqual([o["location"] for o in offers], [self.loc_b, self.loc_a])
        self.assertTrue(offers[0]["is_cheapest"])
        self.assertEqual(offers[0]["extra_pct"], 0)
        self.assertEqual(offers[1]["extra_pct"], 25)
        self.assertEqual(offers[0]["link"], "https://uzum.uz/ru")
        self.assertEqual(ctx["best"], offers[0])

    def test_product_detail_no_offers_and_404(self):
        r = self.client.get(f"/product/{self.meat.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["best"])
        self.assertEqual(r.context["offers"], [])
        self.meat.is_active = False
        self.meat.save()
        self.assertEqual(self.client.get(f"/product/{self.meat.id}/").status_code, 404)
        self.assertEqual(self.client.get("/product/99999/").status_code, 404)

    def test_category_detail(self):
        self.make(product=self.oil, unit="l", price=9000)
        r = self.client.get("/category/gosht/")
        self.assertEqual(r.status_code, 200)
        items = r.context["items"]
        self.assertEqual([i["product"] for i in items], [self.oil, self.meat])  # with offers first
        self.assertEqual(items[0]["offer_count"], 1)
        self.assertIsNone(items[1]["best_offer"])
        self.assertEqual(self.client.get("/category/nope/").status_code, 404)


class CategoryHierarchyTests(BaseData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.food = Category.objects.create(name="Oziq-ovqat", slug="oziq-ovqat", sort_order=10)
        cls.drinks = Category.objects.create(name="Ichimliklar", slug="ichimliklar", sort_order=20)
        cls.gosht = Category.objects.get(slug="gosht")
        cls.gosht.parent = cls.food
        cls.gosht.save()
        cls.tea = Product.objects.create(name="Choy", category=cls.drinks, base_unit="kg")
        cls.direct = Product.objects.create(name="Tuz", category=cls.food, base_unit="kg")

    def test_index_only_top_level_ordered_with_counts(self):
        r = self.client.get("/")
        cats = list(r.context["categories"])
        self.assertEqual([(c.slug, c.product_count) for c in cats],
                         [("oziq-ovqat", 3), ("ichimliklar", 1)])  # 2 in gosht + 1 direct; gosht hidden
        with self.assertNumQueries(1):
            list(Category.objects.filter(parent__isnull=True).annotate(
                product_count=__import__("prices.services", fromlist=["x"]).category_product_count()))

    def test_inactive_children_products_not_counted(self):
        self.oil.is_active = False
        self.oil.save()
        cats = {c.slug: c.product_count for c in self.client.get("/").context["categories"]}
        self.assertEqual(cats["oziq-ovqat"], 2)

    def test_parent_category_page_lists_children_products(self):
        self.make(product=self.oil, unit="l", price=9000)
        r = self.client.get("/category/oziq-ovqat/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({i["product"] for i in r.context["items"]}, {self.meat, self.oil, self.direct})
        subs = r.context["subcategories"]
        self.assertEqual([(c.slug, c.product_count) for c in subs], [("gosht", 2)])
        self.assertIsNone(r.context["parent"])
        self.assertEqual(r.context["category"], self.food)

    def test_child_category_page(self):
        r = self.client.get("/category/gosht/")
        self.assertEqual(r.context["category"], self.gosht)
        self.assertEqual(r.context["parent"], self.food)
        self.assertEqual(r.context["subcategories"], [])
        self.assertEqual({i["product"] for i in r.context["items"]}, {self.meat, self.oil})

    def test_api_parent_count_and_top_filter(self):
        rows = {r["slug"]: r for r in APIClient().get("/api/categories/").json()}
        self.assertEqual(rows["gosht"]["parent"], self.food.id)
        self.assertIsNone(rows["oziq-ovqat"]["parent"])
        self.assertEqual(rows["oziq-ovqat"]["product_count"], 3)
        top = APIClient().get("/api/categories/?top=1").json()
        self.assertEqual([r["slug"] for r in top], ["oziq-ovqat", "ichimliklar"])

    def test_product_detail_parent_reachable(self):
        r = self.client.get(f"/product/{self.meat.id}/")
        self.assertEqual(r.context["product"].category.parent, self.food)

    def test_clean_rejects_self_parent_and_depth(self):
        self.food.parent = self.food
        with self.assertRaises(ValidationError):
            self.food.clean()
        self.food.parent = None
        grandchild = Category(name="X", slug="x", parent=self.gosht)  # gosht already has a parent
        with self.assertRaises(ValidationError):
            grandchild.clean()
        self.food.parent = self.drinks  # food has children -> cannot become a child
        with self.assertRaises(ValidationError):
            self.food.clean()
        ok = Category(name="Y", slug="y", parent=self.drinks)
        ok.clean()


class SeedTopCategoriesMigrationTests(TestCase):
    def test_idempotent_keeps_products_and_admin_edits(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module("prices.migrations.0008_seed_top_categories")
        Product.objects.all().delete()
        Category.objects.all().delete()
        cat = Category.objects.create(name="Go'sht", slug="gosht", emoji="E")
        prod = Product.objects.create(name="Mol", category=cat, base_unit="kg")
        Category.objects.create(name="Kiyimlar (tahrir)", slug="kiyimlar", emoji="Z")  # admin-edited
        mig.forwards(apps, None)
        mig.forwards(apps, None)  # second run must change nothing
        self.assertEqual(Category.objects.filter(parent__isnull=True).count(), 12 + 0)
        food = Category.objects.get(slug="oziq-ovqat")
        self.assertEqual(food.emoji, "🛒")
        self.assertEqual(food.sort_order, 10)
        cat.refresh_from_db()
        self.assertEqual(cat.parent, food)
        self.assertEqual(cat.emoji, "E")
        prod.refresh_from_db()
        self.assertEqual(prod.category_id, cat.id)
        k = Category.objects.get(slug="kiyimlar")
        self.assertEqual((k.name, k.emoji), ("Kiyimlar (tahrir)", "Z"))
        self.assertEqual(Category.objects.filter(slug="kiyimlar").count(), 1)


class SampleProductsTests(TestCase):
    """Runs against the data created by migrations 0008/0009 (not wiped)."""

    def test_every_top_level_category_has_products(self):
        tops = Category.objects.filter(parent__isnull=True)
        self.assertEqual(tops.count(), 12)
        for cat in tops.exclude(slug="oziq-ovqat"):
            self.assertEqual(cat.products.filter(is_active=True).count(), 4, cat.slug)
        self.assertGreaterEqual(Category.objects.get(slug="oziq-ovqat").products.count(), 1)  # fresh DB fallback
        for child in Category.objects.filter(parent__slug="oziq-ovqat"):
            self.assertGreaterEqual(child.products.filter(is_active=True).count(), 2, child.slug)

    def test_rerun_no_duplicates_and_keeps_edits(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module("prices.migrations.0009_seed_sample_products")
        before = Product.objects.count()
        p = Product.objects.get(name="Divan")
        p.description = "Mening tavsifim"
        p.usage = ""
        p.save()
        mig.forwards(apps, None)
        self.assertEqual(Product.objects.count(), before)
        p.refresh_from_db()
        self.assertEqual(p.description, "Mening tavsifim")
        self.assertNotEqual(p.usage, "")  # empty field is refilled
