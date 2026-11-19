"""Server-rendered pages on the new models, and the switch that chooses them over the legacy ones.

The templates are the same files as before: these views hand them the same context keys, so the
pages look identical. Differences while both worlds exist: no category tree (the new Category is flat),
no product image/description/usage, and "district" is simply absent.
"""
from math import ceil

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, Count, IntegerField, Sum, When
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.views.generic import TemplateView

from datetime import timedelta

from apps.catalog.models import Category, Product
from apps.reports.models import Confirmation, PriceReport
from apps.verification import constants as C
from prices import web as legacy_web
from prices.models import Profile

from . import selectors as sel


@method_decorator(ensure_csrf_cookie, name="dispatch")
class NewIndexView(TemplateView):
    template_name = "prices/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.annotate(product_count=sel.category_product_count()) \
            .order_by("sort_order", "name")
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")
class NewProductDetailView(TemplateView):
    template_name = "prices/product_detail.html"

    def get_context_data(self, pk, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = get_object_or_404(Product.objects.select_related("category"), pk=pk, is_active=True)
        offers = sel.build_offers(sel.recent_reports(product=product))
        ctx.update(product=product, offers=offers, best=offers[0] if offers else None, offer_count=len(offers),
                   unit_label=product.get_default_unit_display())
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")
class NewCategoryDetailView(TemplateView):
    template_name = "prices/category.html"

    def get_context_data(self, slug, **kwargs):
        ctx = super().get_context_data(**kwargs)
        category = get_object_or_404(Category, slug=slug)
        products = list(Product.objects.filter(category=category, is_active=True).select_related("category")
                        .order_by("name"))
        by_product = {p.id: [] for p in products}
        for r in sel.recent_reports().filter(product__category=category):
            by_product[r.product_id].append(r)
        items = []
        for p in products:
            offers = sel.build_offers(by_product[p.id])
            items.append({"product": p, "best_offer": offers[0] if offers else None, "offer_count": len(offers)})
        items.sort(key=lambda i: (i["best_offer"] is None,
                                  i["best_offer"]["entry"].normalized_price if i["best_offer"] else 0,
                                  i["product"].name))
        ctx.update(category=category, parent=None, subcategories=[], items=items)
        return ctx


class NewConfirmPricesView(LoginRequiredMixin, TemplateView):
    """Open reports by other people that this user has not confirmed yet; suspicious ones first."""
    template_name = "prices/confirm.html"
    login_url = "/login/"
    LIMIT = 30
    DAYS = 7

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        S = PriceReport.Status
        reports = (
            PriceReport.objects
            .filter(created_at__gte=timezone.now() - timedelta(days=self.DAYS), status__in=(S.PENDING, S.FLAGGED),
                    product__is_active=True, place__is_active=True)
            .exclude(user=user).exclude(confirmations__user=user)
            .select_related("product", "place__city")
            .annotate(n_confirmed=Count("confirmations", distinct=True), w_confirmed=Sum("confirmations__weight"),
                      _flag_first=Case(When(status=S.FLAGGED, then=0), default=1, output_field=IntegerField()))
            .order_by("_flag_first", "n_confirmed", "-created_at", "-id")[:self.LIMIT]
        )
        items = []
        for r in reports:
            flagged = r.status == S.FLAGGED
            missing = C.FLAGGED_CONFIRM_THRESHOLD - (r.w_confirmed or 0)
            items.append({
                "entry": r, "product": r.product.name, "place": f"{r.place.name}, {r.place.city.name}",
                "unit": r.get_unit_display(), "created_at": r.created_at, "flagged": flagged,
                "count": r.n_confirmed, "price_text": f"{r.price:,}".replace(",", " "),
                "quantity": f"{r.quantity.normalize():f}",
                "need_more": max(0, ceil(float(missing))) if flagged else 0,
            })
        ctx["items"] = items
        ctx["my_confirmed"] = Confirmation.objects.filter(user=user).count()
        return ctx


class NewSettingsView(legacy_web.SettingsView):
    """Same page; the price count and the list come from the new reports. Profile saving is unchanged."""

    def get_context_data(self, **kwargs):
        ctx = TemplateView.get_context_data(self, **kwargs)
        user = self.request.user
        profile, _ = Profile.objects.get_or_create(user=user)
        mine = PriceReport.objects.filter(user=user)
        ctx["profile"] = profile
        ctx["my_entries_count"] = mine.count()
        # Dicts, not models: the template reads e.product / e.location / e.get_unit_display either way.
        ctx["recent_entries"] = [
            {"product": r.product, "location": r.place, "created_at": r.created_at, "price": r.price,
             "quantity": r.quantity, "get_unit_display": r.get_unit_display()}
            for r in mine.select_related("product", "place").order_by("-created_at", "-id")[:10]
        ]
        return ctx


class _Switch:
    """Behaves like a class-based view in urls.py; picks the implementation per request from the flag."""

    def __init__(self, legacy_cls, new_cls):
        self.legacy_cls, self.new_cls = legacy_cls, new_cls

    def as_view(self, **initkwargs):
        legacy_view, new_view = self.legacy_cls.as_view(**initkwargs), self.new_cls.as_view(**initkwargs)

        def view(request, *args, **kwargs):
            return (new_view if settings.USE_NEW_API else legacy_view)(request, *args, **kwargs)
        return view


IndexView = _Switch(legacy_web.IndexView, NewIndexView)
ProductDetailView = _Switch(legacy_web.ProductDetailView, NewProductDetailView)
CategoryDetailView = _Switch(legacy_web.CategoryDetailView, NewCategoryDetailView)
ConfirmPricesView = _Switch(legacy_web.ConfirmPricesView, NewConfirmPricesView)
SettingsView = _Switch(legacy_web.SettingsView, NewSettingsView)
