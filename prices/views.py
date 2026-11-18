from collections import defaultdict
from datetime import datetime, time, timedelta
from statistics import median

from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from django_filters.rest_framework import DjangoFilterBackend

from .filters import LocationFilter, PriceEntryFilter, ProductFilter, ProductSearchFilter
from .models import Category, DailyPriceStat, District, Location, PriceAlert, PriceEntry, Product, Region
from .serializers import (CategorySerializer, DistrictSerializer, LocationSerializer,
                          PriceAlertSerializer, PriceEntrySerializer, ProductSerializer, RegionSerializer)
from .permissions import IsSellerOrReadOnly
from .services import (category_product_count, compare_basket, confirm_entry, discount_pct, find_deals,
                       haversine_km, offer_link, quantize_money)
from .throttles import ConfirmThrottle, PriceCreateThrottle


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
    """(lat, lng) floats from ?lat=&lng=, None when absent, 400 when malformed/out of range."""
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


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.annotate(
        product_count=category_product_count()
    ).order_by("sort_order", "name")
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("top") in ("1", "true", "True"):
            qs = qs.filter(parent__isnull=True)
        return qs


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.filter(is_active=True).select_related("category__parent")
    serializer_class = ProductSerializer
    filterset_class = ProductFilter
    filter_backends = [DjangoFilterBackend, ProductSearchFilter]

    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def cheapest(self, request, pk=None):
        product = self.get_object()
        days = _int_param(request, "days", 7)
        district = _district_param(request)
        since = timezone.now() - timedelta(days=days)
        qs = PriceEntry.objects.filter(
            product=product, is_flagged=False, created_at__gte=since, location__is_active=True
        ).select_related("location__district")
        if district:
            qs = qs.filter(location__district_id=district)

        latest = {}
        for entry in qs.order_by("-created_at", "-id"):  # newest first -> first seen wins
            latest.setdefault(entry.location_id, entry)

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

        def distance(e):
            loc = e.location
            if user_pos is None or loc.lat is None or loc.lng is None:
                return None
            return round(haversine_km(user_pos[0], user_pos[1], loc.lat, loc.lng), 2)

        entries = []
        for e in latest.values():
            d = distance(e)
            if max_km is not None and (d is None or d > max_km):
                continue
            entries.append((e, d))
        if sort == "distance":
            entries.sort(key=lambda t: (t[1] is None, t[1] or 0, t[0].normalized_price))
        else:
            entries.sort(key=lambda t: (t[0].normalized_price, -t[0].created_at.timestamp()))

        results = [
            {
                "distance_km": d,
                "location": LocationSerializer(e.location).data,
                "link": offer_link(e)[0],
                "link_kind": offer_link(e)[1],
                "is_promo": e.is_promo,
                "old_price": e.old_price,
                "normalized_price": e.normalized_price,
                "price": e.price,
                "quantity": e.quantity,
                "unit": e.unit,
                "base_unit": product.base_unit,
                "created_at": e.created_at,
            }
            for e, d in entries
        ]
        return Response({"product": product.id, "days": days, "results": results})

    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def trend(self, request, pk=None):
        product = self.get_object()
        days = _int_param(request, "days", 30)
        district = _district_param(request)
        since = (timezone.localtime() - timedelta(days=days)).date()

        stats = DailyPriceStat.objects.filter(product=product, date__gte=since)
        if district:
            stats = stats.filter(location__district_id=district)

        by_day = defaultdict(lambda: {"min": [], "max": [], "med": [], "count": 0})
        for s in stats:
            d = by_day[s.date]
            d["min"].append(s.min_price)
            d["max"].append(s.max_price)
            d["med"].append(s.median_price)
            d["count"] += s.count
        aggregated_days = set(by_day)

        # Fill every day that has no DailyPriceStat rows yet (typically "today",
        # or any day the cron missed) live from raw entries. Grouped per location
        # first, so live points are computed exactly like aggregated ones.
        entries = PriceEntry.objects.filter(
            product=product, is_flagged=False,
            created_at__gte=timezone.make_aware(datetime.combine(since, time.min)),
        )
        if district:
            entries = entries.filter(location__district_id=district)
        raw = defaultdict(list)  # (day, location_id) -> [normalized prices]
        for created_at, location_id, value in entries.values_list(
            "created_at", "location_id", "normalized_price"
        ):
            day = timezone.localtime(created_at).date()
            if day not in aggregated_days:
                raw[(day, location_id)].append(value)
        for (day, _location_id), values in raw.items():
            d = by_day[day]
            d["min"].append(min(values))
            d["max"].append(max(values))
            d["med"].append(median(values))
            d["count"] += len(values)

        live_days = set(by_day) - aggregated_days
        if not live_days:
            source = "daily_stats"
        elif not aggregated_days:
            source = "live"
        else:
            source = "mixed"

        points = [
            {
                "date": day,
                "median_price": quantize_money(median(d["med"])),
                "min_price": min(d["min"]),
                "max_price": max(d["max"]),
                "count": d["count"],
                "live": day in live_days,
            }
            for day, d in sorted(by_day.items())
        ]
        return Response({"product": product.id, "days": days, "source": source, "points": points})


class RegionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    pagination_class = None


class DistrictViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = District.objects.all()
    serializer_class = DistrictSerializer
    filterset_fields = ["region"]
    pagination_class = None


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Location.objects.filter(is_active=True).select_related("district")
    serializer_class = LocationSerializer
    filterset_class = LocationFilter
    search_fields = ["name", "address"]


class PriceEntryViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = PriceEntrySerializer
    filterset_class = PriceEntryFilter
    permission_classes = [IsSellerOrReadOnly]
    throttle_classes = [PriceCreateThrottle]
    throttle_scope = "price_create"

    def get_queryset(self):
        return PriceEntry.objects.filter(is_flagged=False).select_related(
            "product", "location"
        ).annotate(confirmation_count=Count("confirmations")).order_by("-created_at", "-id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated],
            throttle_classes=[ConfirmThrottle], throttle_scope="price_confirm",
            filter_backends=[], pagination_class=None)
    def confirm(self, request, pk=None):
        """Vouch for a price. Flagged entries are reachable here so the community can clear them."""
        entry = get_object_or_404(PriceEntry, pk=pk)
        created, count = confirm_entry(entry, request.user)
        return Response({"id": entry.pk, "confirmations": count, "is_flagged": entry.is_flagged},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


def _abs(request, image):
    return request.build_absolute_uri(image.url) if image else None


class DealsView(APIView):
    """Public marketplace feed: promo offers and 'cheaper than elsewhere' offers."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        reason = request.query_params.get("reason", "all")
        if reason not in ("all", "promo", "cheaper"):
            raise ValidationError({"reason": "Must be one of: all, promo, cheaper."})
        limit = _int_param(request, "limit", 12, maximum=48)
        district = _district_param(request)
        category = request.query_params.get("category") or None

        results = []
        for e, why, pct in find_deals(reason, category=category, district=district)[:limit]:
            link, kind = offer_link(e)
            loc = e.location
            results.append({
                "product": {
                    "id": e.product_id, "name": e.product.name, "image": _abs(request, e.product.image),
                    "category_name": e.product.category.name, "base_unit": e.product.base_unit,
                },
                "offer": {
                    "price": e.price, "quantity": e.quantity, "unit": e.unit,
                    "unit_label": e.get_unit_display(), "normalized_price": e.normalized_price,
                    "old_price": e.old_price, "is_promo": e.is_promo, "discount_pct": discount_pct(e),
                    "location": {"id": loc.id, "name": loc.name, "type": loc.type,
                                 "district_name": loc.district.name, "address": loc.address},
                    "link": link, "link_kind": kind, "created_at": e.created_at,
                },
                "reason": why,
                "saving_pct": pct,
            })
        return Response({"results": results})


class PriceAlertViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
                        mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """The caller's own price alerts. Delivery is done by `manage.py check_price_alerts`."""
    serializer_class = PriceAlertSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user).select_related("product")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


BASKET_MAX_ITEMS = 50


class BasketCompareView(APIView):
    """POST {"items": [{"product": 1, "quantity": 2.5}, ...]} (quantity in the product's base unit).
    Returns per-store totals; stores that carry every item come first."""
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

        result = compare_basket(items)
        stores = []
        for r in result["stores"]:
            loc = r["location"]
            some_entry = next(iter(r["lines"].values()))
            link, kind = offer_link(some_entry)
            stores.append({
                "location": {"id": loc.id, "name": loc.name, "type": loc.type,
                             "district_name": loc.district.name, "address": loc.address},
                "link": link, "link_kind": kind,
                "total": r["total"], "complete": not r["missing"], "missing": r["missing"],
                "lines": [{"product": pid, "quantity": items[pid],
                           "normalized_price": r["lines"][pid].normalized_price,
                           "line_total": quantize_money(r["lines"][pid].normalized_price * items[pid])}
                          for pid in items if pid in r["lines"]],
            })
        complete = [s for s in stores if s["complete"]]
        best = complete[0] if complete else None
        split = result["split_total"]
        return Response({
            "stores": stores,
            "best_store": best["location"]["id"] if best else None,
            "best_store_total": best["total"] if best else None,
            "split_total": split,  # cheapest item-by-item across stores (needs several trips)
            "split_saving": (quantize_money(best["total"] - split) if best else None),
            "unpriced": result["unpriced"],
            "products": {pid: {"name": p.name, "base_unit": p.base_unit} for pid, p in products.items()},
        })
