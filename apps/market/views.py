"""Read API on the new models, returning the SAME JSON shapes as the legacy /api/ so the existing
pages and app.js work unchanged. Mounted at /api/v2/.

Compatibility notes (all temporary, until the pages are switched and the legacy app is removed):
  * "district" in the API is the new City (id and name), because Place has a city and no district.
  * Unit codes are emitted in the legacy spelling (litr -> l, dona -> piece), see selectors.UNIT_OUT.
  * Category emoji is always empty and categories are flat (parent is null).
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from difflib import get_close_matches
from math import asin, cos, radians, sin, sqrt
from statistics import median

from django.db.models import Case, IntegerField, Q, When
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
import django_filters
from rest_framework import filters as drf_filters
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Category, City, Place, Product
from apps.catalog.textnorm import search_tokens
from apps.reports.models import PriceReport

from . import selectors as sel
from .selectors import api_unit

BASE_UNIT_OUT = {"kg": "kg", "litr": "l", "dona": "piece"}


def _abs_image(request, image):
    if not image:
        return None
    return request.build_absolute_uri(image.url) if request else image.url


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200


# ---------------------------------------------------------------- serializers
class CategorySerializer(serializers.ModelSerializer):
    emoji = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    parent = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "emoji", "image", "parent", "product_count")

    def get_emoji(self, obj):
        return ""

    def get_image(self, obj):
        return _abs_image(self.context.get("request"), obj.image)

    def get_parent(self, obj):
        return None

    def get_product_count(self, obj):
        annotated = getattr(obj, "product_count", None)
        return annotated if annotated is not None else obj.products.filter(is_active=True).count()


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    base_unit = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ("id", "name", "category", "category_name", "base_unit", "is_active", "image", "description", "usage")

    def get_base_unit(self, obj):
        return BASE_UNIT_OUT[obj.default_unit]

    def get_image(self, obj):
        return _abs_image(self.context.get("request"), obj.image)


class DistrictSerializer(serializers.ModelSerializer):
    region = serializers.SerializerMethodField()

    class Meta:
        model = City
        fields = ("id", "name", "region")

    def get_region(self, obj):
        return None


class PlaceSerializer(serializers.ModelSerializer):
    district = serializers.IntegerField(source="city_id", read_only=True)
    district_name = serializers.CharField(source="city.name", read_only=True)

    class Meta:
        model = Place
        fields = ("id", "name", "type", "district", "district_name", "address", "website", "lat", "lng", "is_active")


def place_brief(place):
    return {"id": place.id, "name": place.name, "type": place.type,
            "district_name": place.city.name, "address": place.address}


# ---------------------------------------------------------------- filters
class ProductFilter(django_filters.FilterSet):
    class Meta:
        model = Product
        fields = ["category"]


class PlaceFilter(django_filters.FilterSet):
    district = django_filters.NumberFilter(field_name="city_id")

    class Meta:
        model = Place
        fields = ["district", "type"]


class ProductSearchFilter(drf_filters.SearchFilter):
    """?search=... ignoring case, spaces, apostrophes and Cyrillic/Latin differences. Every word must match
    the product name OR one of its aliases ("govyadina" finds "Mol go'shti"). Falls back to close spellings."""

    def filter_queryset(self, request, queryset, view):
        tokens = search_tokens(request.query_params.get(self.search_param, ""))
        if not tokens:
            return queryset
        strict = queryset
        for token in tokens:
            strict = strict.filter(Q(search_key__contains=token) | Q(aliases__search_key__contains=token))
        strict = strict.distinct()
        if strict.exists():
            starts = Case(When(search_key__startswith=tokens[0], then=0), default=1, output_field=IntegerField())
            return queryset.filter(pk__in=strict.values("pk")).annotate(_rank=starts).order_by("_rank", "name")

        joined = "".join(tokens)
        rows = list(queryset.values_list("pk", "search_key")[:5000])
        by_key = {}
        for pk, key in rows:
            by_key.setdefault(key, []).append(pk)
        wanted = set(get_close_matches(joined, by_key, n=8, cutoff=0.7))
        for pk, key in rows:
            if any(len(t) >= 4 and key.startswith(t[:4]) and get_close_matches(t, [key[:len(t) + 2]], n=1, cutoff=0.8)
                   for t in tokens):
                wanted.add(key)
        return queryset.filter(pk__in=[pk for key in wanted for pk in by_key[key]])


# ---------------------------------------------------------------- query params
def _int_param(request, name, default, maximum=365):
    raw = request.query_params.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: "Must be an integer."})
    if not 1 <= value <= maximum:
        raise ValidationError({name: f"Must be between 1 and {maximum}."})
    return value


def _district_param(request):
    raw = request.query_params.get("district")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({"district": "Must be an integer."})


def _coords(request):
    lat, lng = request.query_params.get("lat"), request.query_params.get("lng")
    if lat in (None, "") and lng in (None, ""):
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValidationError({"lat": "lat and lng must both be numbers."})
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValidationError({"lat": "Coordinates out of range."})
    return lat, lng


def _haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = (radians(float(v)) for v in (lat1, lng1, lat2, lng2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(a))


# ---------------------------------------------------------------- viewsets
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.annotate(product_count=sel.category_product_count()).order_by("sort_order", "name")
    serializer_class = CategorySerializer
    pagination_class = None


class DistrictViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = City.objects.all()
    serializer_class = DistrictSerializer
    pagination_class = None


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Place.objects.filter(is_active=True).select_related("city")
    serializer_class = PlaceSerializer
    filterset_class = PlaceFilter
    search_fields = ["name", "address"]
    pagination_class = StandardPagination


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.filter(is_active=True).select_related("category")
    serializer_class = ProductSerializer
    filterset_class = ProductFilter
    filter_backends = [DjangoFilterBackend, ProductSearchFilter]
    pagination_class = StandardPagination

    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def cheapest(self, request, pk=None):
        product = self.get_object()
        days = _int_param(request, "days", 7)
        city = _district_param(request)
        since = timezone.now() - timedelta(days=days)
        qs = PriceReport.objects.filter(product=product, status__in=sel.VISIBLE_STATUSES, created_at__gte=since,
                                        place__is_active=True).select_related("place__city")
        if city:
            qs = qs.filter(place__city_id=city)
        latest = {}
        for r in qs.order_by("-created_at", "-id"):
            latest.setdefault(r.place_id, r)

        user_pos = _coords(request)
        sort = request.query_params.get("sort", "price")
        if sort not in ("price", "distance"):
            raise ValidationError({"sort": "Must be 'price' or 'distance'."})
        if sort == "distance" and user_pos is None:
            raise ValidationError({"lat": "lat and lng are required for sort=distance."})
        max_km = request.query_params.get("max_km")
        if max_km not in (None, ""):
            try:
                max_km = float(max_km)
            except ValueError:
                raise ValidationError({"max_km": "Must be a number."})
            if max_km <= 0 or user_pos is None:
                raise ValidationError({"max_km": "Must be positive and needs lat and lng."})
        else:
            max_km = None

        def distance(r):
            p = r.place
            if user_pos is None or p.lat is None or p.lng is None:
                return None
            return round(_haversine_km(user_pos[0], user_pos[1], p.lat, p.lng), 2)

        entries = []
        for r in latest.values():
            d = distance(r)
            if max_km is not None and (d is None or d > max_km):
                continue
            entries.append((r, d))
        if sort == "distance":
            entries.sort(key=lambda t: (t[1] is None, t[1] or 0, t[0].normalized_price))
        else:
            entries.sort(key=lambda t: (t[0].normalized_price, -t[0].created_at.timestamp()))

        changes = sel.changes_for(r for r, _ in entries)
        results = []
        for r, d in entries:
            link, kind = sel.offer_link(r)
            results.append({
                "change": changes[r.pk], "distance_km": d, "location": PlaceSerializer(r.place).data,
                "link": link, "link_kind": kind, "is_promo": r.is_promo, "old_price": r.old_price,
                "normalized_price": r.normalized_price, "price": r.price, "quantity": r.quantity,
                "unit": api_unit(r.unit), "base_unit": BASE_UNIT_OUT[product.default_unit],
                "created_at": r.created_at,
            })
        return Response({"product": product.id, "days": days, "results": results})

    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def trend(self, request, pk=None):
        """Daily price line computed live from reports: per day the median of each place's median."""
        product = self.get_object()
        days = _int_param(request, "days", 30)
        city = _district_param(request)
        since = (timezone.localtime() - timedelta(days=days)).date()
        qs = PriceReport.objects.filter(
            product=product, status__in=sel.VISIBLE_STATUSES, place__is_active=True,
            created_at__gte=timezone.make_aware(datetime.combine(since, time.min)))
        if city:
            qs = qs.filter(place__city_id=city)

        per_place = defaultdict(list)  # (day, place_id) -> normalized prices
        for created_at, place_id, value in qs.values_list("created_at", "place_id", "normalized_price"):
            per_place[(timezone.localtime(created_at).date(), place_id)].append(value)
        by_day = defaultdict(lambda: {"min": [], "max": [], "med": [], "count": 0})
        for (day, _place), values in per_place.items():
            d = by_day[day]
            d["min"].append(min(values))
            d["max"].append(max(values))
            d["med"].append(median(values))
            d["count"] += len(values)

        today = timezone.localtime().date()
        points = [{"date": day, "median_price": sel.quantize_money(median(d["med"])), "min_price": min(d["min"]),
                   "max_price": max(d["max"]), "count": d["count"], "live": day == today}
                  for day, d in sorted(by_day.items())]
        return Response({"product": product.id, "days": days, "source": "live", "points": points})


# ---------------------------------------------------------------- deals and basket
class DealsView(APIView):
    """Promo offers and 'cheaper than elsewhere' offers."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        reason = request.query_params.get("reason", "all")
        if reason not in ("all", "promo", "cheaper"):
            raise ValidationError({"reason": "Must be one of: all, promo, cheaper."})
        limit = _int_param(request, "limit", 12, maximum=48)
        deals = sel.find_deals(reason, category=request.query_params.get("category") or None,
                               city=_district_param(request))[:limit]
        changes = sel.changes_for(r for r, _, _ in deals)
        results = []
        for r, why, value in deals:
            link, kind = sel.offer_link(r)
            results.append({
                "product": {"id": r.product_id, "name": r.product.name, "image": _abs_image(request, r.product.image),
                            "category_name": r.product.category.name,
                            "base_unit": BASE_UNIT_OUT[r.product.default_unit]},
                "offer": {"price": r.price, "quantity": r.quantity, "unit": api_unit(r.unit),
                          "unit_label": r.get_unit_display(), "normalized_price": r.normalized_price,
                          "old_price": r.old_price, "is_promo": r.is_promo, "discount_pct": sel.discount_pct(r),
                          "location": place_brief(r.place), "link": link, "link_kind": kind,
                          "created_at": r.created_at, "change": changes[r.pk]},
                "reason": why, "saving_pct": value,
            })
        return Response({"results": results})


class ProductIdMapView(APIView):
    """{"to_v2": {legacy id: new id}, "to_legacy": {new id: legacy id}}, matched by product name.
    Lets the browser translate saved favorites and cart when the site switches catalogs."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        from prices.models import Product as LegacyProduct
        new = dict(Product.objects.values_list("name", "id"))
        pairs = [(legacy_id, new[name]) for name, legacy_id in LegacyProduct.objects.values_list("name", "id")
                 if name in new]
        return Response({"to_v2": {str(old): fresh for old, fresh in pairs},
                         "to_legacy": {str(fresh): old for old, fresh in pairs}})


BASKET_MAX_ITEMS = 50


class BasketCompareView(APIView):
    """POST {"items": [{"product": 1, "quantity": 2.5}, ...]} (quantity in the product's base unit)."""
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        raw = request.data.get("items") if hasattr(request.data, "get") else None
        if not isinstance(raw, list) or not raw:
            raise ValidationError({"items": "A non-empty list is required."})
        if len(raw) > BASKET_MAX_ITEMS:
            raise ValidationError({"items": f"At most {BASKET_MAX_ITEMS} items."})
        items = {}
        for row in raw:
            try:
                pid = int(row["product"])
                qty = Decimal(str(row.get("quantity", 1)))
            except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
                raise ValidationError({"items": "Each item needs an integer 'product' and numeric 'quantity'."})
            if not qty.is_finite() or not Decimal("0") < qty <= Decimal("10000"):
                raise ValidationError({"items": "quantity must be in (0, 10000]."})
            items[pid] = items.get(pid, Decimal("0")) + qty

        products = {p.pk: p for p in Product.objects.filter(pk__in=items, is_active=True)}
        unknown = [pid for pid in items if pid not in products]
        if unknown:
            raise ValidationError({"items": f"Unknown or inactive products: {sorted(unknown)}"})

        result = sel.compare_basket(items)
        stores = []
        for r in result["stores"]:
            some = next(iter(r["lines"].values()))
            link, kind = sel.offer_link(some)
            stores.append({
                "location": place_brief(r["place"]), "link": link, "link_kind": kind,
                "total": r["total"], "complete": not r["missing"], "missing": r["missing"],
                "lines": [{"product": pid, "quantity": items[pid],
                           "normalized_price": r["lines"][pid].normalized_price,
                           "line_total": sel.quantize_money(r["lines"][pid].normalized_price * items[pid])}
                          for pid in items if pid in r["lines"]],
            })
        complete = [s for s in stores if s["complete"]]
        best = complete[0] if complete else None
        split = result["split_total"]
        return Response({
            "stores": stores,
            "best_store": best["location"]["id"] if best else None,
            "best_store_total": best["total"] if best else None,
            "split_total": split,
            "split_saving": sel.quantize_money(best["total"] - split) if best else None,
            "unpriced": result["unpriced"],
            "products": {pid: {"name": p.name, "base_unit": BASE_UNIT_OUT[p.default_unit]}
                         for pid, p in products.items()},
        })
