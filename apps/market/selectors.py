"""Read-side price logic on the new models (PriceReport / Place / Product).

Mirrors prices/services.py so the v2 API can return the same JSON as the legacy one while the
site moves over. Everything is per ONE product.default_unit (normalized_price).
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from urllib.parse import quote, urlparse

from django.db.models import Count, Q
from django.utils import timezone

from apps.reports.models import PriceReport

# Which reports the price lists may show. PENDING = not yet confirmed by others.
# One place to change if the product decision changes (e.g. confirmed only).
VISIBLE_STATUSES = (PriceReport.Status.PENDING, PriceReport.Status.CONFIRMED)

RECENT_DAYS = 30
CHEAPER_MIN_PCT = Decimal("10")

# New unit codes -> the codes the existing pages and JS already understand.
UNIT_OUT = {"kg": "kg", "g": "g", "litr": "l", "ml": "ml", "dona": "piece", "qop": "qop"}
UNIT_IN = {v: k for k, v in UNIT_OUT.items()}


def api_unit(code):
    return UNIT_OUT.get(code, code)


def quantize_money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def whole_pct(numerator, base):
    """Whole percent of numerator / base, rounded half up."""
    return int((Decimal(numerator) / Decimal(base) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def category_product_count():
    return Count("products", filter=Q(products__is_active=True), distinct=True)


def recent_reports(product=None, since_days=RECENT_DAYS):
    """Visible, recent reports for active products and places, newest first."""
    qs = PriceReport.objects.filter(
        status__in=VISIBLE_STATUSES, product__is_active=True, place__is_active=True,
        created_at__gte=timezone.now() - timedelta(days=since_days),
    ).select_related("product__category", "place__city")
    if product is not None:
        qs = qs.filter(product=product)
    return qs.order_by("-created_at", "-id")


def latest_per_place(reports):
    """Keep only the newest report per (product, place). `reports` must be newest first."""
    seen = {}
    for r in reports:
        seen.setdefault((r.product_id, r.place_id), r)
    return list(seen.values())


# ---------------------------------------------------------------- links
def _is_http(value):
    return bool(value) and urlparse(value).scheme.lower() in ("http", "https")


def offer_link(report):
    """(url, kind): direct product link > store website > map."""
    if _is_http(report.source_url):
        return report.source_url, "store"
    place = report.place
    if _is_http(place.website):
        return place.website, "store"
    if place.lat is not None and place.lng is not None:
        return f"https://www.google.com/maps?q={place.lat},{place.lng}", "map"
    query = quote(", ".join(p for p in (place.name, place.address, place.city.name) if p))
    return "https://www.google.com/maps/search/?api=1&query=" + query, "map"


# ---------------------------------------------------------------- change vs previous price
def price_change(report, previous):
    """{"dir": up|down|same, "pct": signed whole percent, "old_price"} or None without a previous price."""
    if previous is None or not previous.normalized_price:
        return None
    value = whole_pct(report.normalized_price - previous.normalized_price, previous.normalized_price)
    return {"dir": "up" if value > 0 else "down" if value < 0 else "same", "pct": value,
            "old_price": previous.normalized_price}


def attach_changes(targets, history):
    """{report.pk: price_change or None}. `history` is newest first."""
    by_place = {}
    for r in history:
        by_place.setdefault((r.product_id, r.place_id), []).append(r)
    out = {}
    for t in targets:
        older = next((x for x in by_place.get((t.product_id, t.place_id), ())
                      if (x.created_at, x.pk) < (t.created_at, t.pk)), None)
        out[t.pk] = price_change(t, older)
    return out


def changes_for(targets):
    targets = list(targets)
    if not targets:
        return {}
    return attach_changes(targets, recent_reports().filter(product_id__in={t.product_id for t in targets}))


# ---------------------------------------------------------------- offers and deals
def discount_pct(report):
    if report.is_promo and report.old_price and report.old_price > report.price:
        return whole_pct(report.old_price - report.price, report.old_price)
    return None


def find_deals(reason="all", category=None, city=None):
    """One deal per product (promo beats 'cheaper elsewhere'), biggest saving first.
    Returns [(report, reason, saving_pct)]."""
    reports = recent_reports()
    if category:
        reports = reports.filter(product__category__slug=category)
    if city:
        reports = reports.filter(place__city_id=city)
    by_product = {}
    for r in latest_per_place(reports):
        by_product.setdefault(r.product_id, []).append(r)

    deals = []
    for items in by_product.values():
        if reason in ("promo", "all"):
            promos = [(discount_pct(r), r) for r in items if discount_pct(r)]
            if promos:
                value, r = max(promos, key=lambda t: (t[0], -t[1].normalized_price))
                deals.append((r, "promo", value))
                continue
        if reason in ("cheaper", "all") and len(items) >= 2:
            best = None
            for r in items:
                others = sorted(o.normalized_price for o in items if o.pk != r.pk)
                med = median(others)
                if med <= 0:
                    continue
                saving = (med - r.normalized_price) / med * 100
                if saving >= CHEAPER_MIN_PCT and (best is None or saving > best[0]):
                    best = (saving, r)
            if best:
                deals.append((best[1], "cheaper", int(best[0].quantize(Decimal("1"), rounding=ROUND_HALF_UP))))
    deals.sort(key=lambda d: (-d[2], d[0].normalized_price))
    return deals


# ---------------------------------------------------------------- basket
def compare_basket(items):
    """items: {product_id: Decimal quantity in the product's default unit}.
    Stores holding every item rank first (cheapest total); the rest follow with their missing ids."""
    reports = latest_per_place(recent_reports().filter(product_id__in=list(items)))
    stores, best_per_product = {}, {}
    for r in reports:
        s = stores.setdefault(r.place_id, {"place": r.place, "lines": {}})
        s["lines"][r.product_id] = r
        cur = best_per_product.get(r.product_id)
        if cur is None or r.normalized_price < cur.normalized_price:
            best_per_product[r.product_id] = r

    results = []
    for s in stores.values():
        total = sum((s["lines"][pid].normalized_price * qty for pid, qty in items.items() if pid in s["lines"]),
                    Decimal("0"))
        missing = [pid for pid in items if pid not in s["lines"]]
        results.append({"place": s["place"], "total": quantize_money(total), "missing": missing, "lines": s["lines"]})
    results.sort(key=lambda r: (bool(r["missing"]), len(r["missing"]), r["total"]))

    split_total = sum((best_per_product[pid].normalized_price * qty for pid, qty in items.items()
                       if pid in best_per_product), Decimal("0"))
    return {"stores": results, "split_total": quantize_money(split_total),
            "best_per_product": best_per_product,
            "unpriced": [pid for pid in items if pid not in best_per_product]}
