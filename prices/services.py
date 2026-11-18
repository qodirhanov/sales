from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from urllib.parse import quote, urlparse

from django.db.models import Count, Q
from django.utils import timezone


def category_product_count():
    """Annotation: active products in the category plus those in its children (one query, no N+1).
    distinct=True is required because the two joins multiply rows."""
    return (Count("products", filter=Q(products__is_active=True), distinct=True)
            + Count("children__products", filter=Q(children__products__is_active=True), distinct=True))

OUTLIER_WINDOW_DAYS = 30
OUTLIER_MIN_SAMPLES = 3
OUTLIER_MAX_DEVIATION = Decimal("0.5")

RECENT_DAYS = 30
CHEAPER_MIN_PCT = Decimal("10")


def quantize_money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def flag_if_outlier(entry):
    """Set entry.is_flagged=True if its normalized_price deviates >50% from the
    30-day median of non-flagged entries of the same product (needs >=3 samples).
    Must be called before the entry is saved (normalized_price already computed)."""
    since = timezone.now() - timedelta(days=OUTLIER_WINDOW_DAYS)
    values = list(
        type(entry).objects.filter(
            product_id=entry.product_id, created_at__gte=since, is_flagged=False
        ).values_list("normalized_price", flat=True)
    )
    if len(values) < OUTLIER_MIN_SAMPLES:
        return False
    med = median(values)
    if med <= 0:
        return False
    deviation = abs(entry.normalized_price - med) / med
    if deviation > OUTLIER_MAX_DEVIATION:
        entry.is_flagged = True
    return entry.is_flagged


# ---------------------------------------------------------------- marketplace helpers
def is_http_url(value):
    return bool(value) and urlparse(value).scheme.lower() in ("http", "https")


def offer_link(entry):
    """(url, kind) for where to buy: direct product link > store website > map."""
    if is_http_url(entry.source_url):
        return entry.source_url, "store"
    loc = entry.location
    if is_http_url(loc.website):
        return loc.website, "store"
    if loc.lat is not None and loc.lng is not None:
        return f"https://www.google.com/maps?q={loc.lat},{loc.lng}", "map"
    parts = [loc.name, loc.address, loc.district.name]
    query = quote(", ".join(p for p in parts if p))
    return "https://www.google.com/maps/search/?api=1&query=" + query, "map"


def recent_entries(product=None, since_days=RECENT_DAYS):
    """Valid (non-flagged, active product + location, recent) entries, newest first."""
    from .models import PriceEntry

    qs = PriceEntry.objects.filter(
        is_flagged=False, product__is_active=True, location__is_active=True,
        created_at__gte=timezone.now() - timedelta(days=since_days),
    ).select_related("product__category", "location__district")
    if product is not None:
        qs = qs.filter(product=product)
    return qs.order_by("-created_at", "-id")


def latest_per_location(entries):
    """Keep only the newest entry per (product, location). `entries` must be newest first."""
    seen = {}
    for e in entries:
        seen.setdefault((e.product_id, e.location_id), e)
    return list(seen.values())


def discount_pct(entry):
    if entry.is_promo and entry.old_price and entry.old_price > entry.price:
        return int(((entry.old_price - entry.price) / entry.old_price * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    return None


def build_offer(entry, cheapest_price=None):
    """Dict consumed by the web templates."""
    link, kind = offer_link(entry)
    extra = 0
    if cheapest_price:
        extra = int(((entry.normalized_price - cheapest_price) / cheapest_price * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    return {
        "entry": entry,
        "location": entry.location,
        "link": link,
        "link_kind": kind,
        "is_cheapest": bool(cheapest_price) and entry.normalized_price == cheapest_price,
        "extra_pct": extra,
        "is_promo": entry.is_promo,
        "old_price": entry.old_price,
        "discount_pct": discount_pct(entry),
    }


def build_offers(entries):
    """Offers sorted by normalized price asc, from newest-first entries of ONE product."""
    latest = sorted(latest_per_location(entries),
                    key=lambda e: (e.normalized_price, -e.created_at.timestamp()))
    cheapest = latest[0].normalized_price if latest else None
    return [build_offer(e, cheapest) for e in latest]


def find_deals(reason="all", category=None, district=None):
    """One deal per product (promo wins over 'cheaper elsewhere'), saving desc.
    Returns a list of (entry, reason, saving_pct)."""
    entries = recent_entries()
    if category:
        entries = entries.filter(product__category__slug=category)
    if district:
        entries = entries.filter(location__district_id=district)

    by_product = {}
    for e in latest_per_location(entries):
        by_product.setdefault(e.product_id, []).append(e)

    deals = []
    for items in by_product.values():
        if reason in ("promo", "all"):
            promos = [(discount_pct(e), e) for e in items if discount_pct(e)]
            if promos:
                pct, e = max(promos, key=lambda t: (t[0], -t[1].normalized_price))
                deals.append((e, "promo", pct))
                continue
        if reason in ("cheaper", "all") and len(items) >= 2:
            best = None
            for e in items:
                others = sorted(o.normalized_price for o in items if o.pk != e.pk)
                med = median(others)
                if med <= 0:
                    continue
                saving = (med - e.normalized_price) / med * 100
                if saving >= CHEAPER_MIN_PCT and (best is None or saving > best[0]):
                    best = (saving, e)
            if best:
                pct = int(best[0].quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                deals.append((best[1], "cheaper", pct))
    deals.sort(key=lambda d: (-d[2], d[0].normalized_price))
    return deals


# ---------------------------------------------------------------- confirmations
CONFIRMATIONS_TO_UNFLAG = 2


def confirm_entry(entry, user):
    """Record `user`'s confirmation. Returns (created, count). A flagged entry that reaches
    CONFIRMATIONS_TO_UNFLAG distinct confirmations is cleared. Authors cannot confirm themselves."""
    from django.core.exceptions import PermissionDenied

    from .models import PriceConfirmation

    if entry.user_id == user.id:
        raise PermissionDenied("O'z narxingizni tasdiqlay olmaysiz.")
    _, created = PriceConfirmation.objects.get_or_create(entry=entry, user=user)
    count = entry.confirmations.count()
    if entry.is_flagged and count >= CONFIRMATIONS_TO_UNFLAG:
        type(entry).objects.filter(pk=entry.pk).update(is_flagged=False)
        entry.is_flagged = False
    return created, count


# ---------------------------------------------------------------- nearest store
def haversine_km(lat1, lng1, lat2, lng2):
    from math import asin, cos, radians, sin, sqrt

    lat1, lng1, lat2, lng2 = map(lambda v: radians(float(v)), (lat1, lng1, lat2, lng2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(a))


# ---------------------------------------------------------------- basket comparison
def compare_basket(items):
    """items: {product_id: Decimal quantity in the product's base unit}.
    Returns dict with per-store totals. Stores holding every item rank first (cheapest total);
    stores missing some items are listed after, with `missing` product ids."""
    entries = latest_per_location(recent_entries().filter(product_id__in=list(items)))
    stores = {}
    best_per_product = {}
    for e in entries:
        s = stores.setdefault(e.location_id, {"location": e.location, "lines": {}})
        s["lines"][e.product_id] = e
        cur = best_per_product.get(e.product_id)
        if cur is None or e.normalized_price < cur.normalized_price:
            best_per_product[e.product_id] = e

    results = []
    for s in stores.values():
        total = sum((s["lines"][pid].normalized_price * qty for pid, qty in items.items() if pid in s["lines"]),
                    Decimal("0"))
        missing = [pid for pid in items if pid not in s["lines"]]
        results.append({"location": s["location"], "total": quantize_money(total), "missing": missing,
                        "lines": s["lines"]})
    results.sort(key=lambda r: (bool(r["missing"]), len(r["missing"]), r["total"]))

    split_total = sum((best_per_product[pid].normalized_price * qty
                       for pid, qty in items.items() if pid in best_per_product), Decimal("0"))
    unpriced = [pid for pid in items if pid not in best_per_product]
    return {"stores": results, "split_total": quantize_money(split_total),
            "best_per_product": best_per_product, "unpriced": unpriced}


# ---------------------------------------------------------------- price alerts
def best_current_price(product):
    """Lowest recent normalized price for a product, or None."""
    prices = [e.normalized_price for e in latest_per_location(recent_entries(product=product))]
    return min(prices) if prices else None


def alert_is_due(alert, best):
    """Fire when best <= target and it is new (never notified) or cheaper than the last notification."""
    if best is None or best > alert.target_price:
        return False
    return alert.last_notified_price is None or best < alert.last_notified_price
