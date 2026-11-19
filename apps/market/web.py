"""Server-rendered pages on the new models, and the switch that chooses them over the legacy ones.

The templates are the same files as before: these views hand them the same context keys, so the
pages look identical. Differences while both worlds exist: no category tree (the new Category is flat),
no product image/description/usage, and "district" is simply absent.
"""
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

from apps.catalog.models import Category, Product
from prices import web as legacy_web

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
