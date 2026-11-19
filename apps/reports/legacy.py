"""One-way, repeatable copy of the legacy `prices` app data into `apps.*`.

Run through `manage.py import_legacy_prices`. It never modifies or deletes legacy rows, and running it
again only adds what is missing, so it is safe to use while the old app is still live.

What maps to what
  Region                 -> catalog.City (or the single city given with --city)
  Location (+ District)  -> catalog.Place; the district name is folded into the address
  Category (parent/child)-> catalog.Category, flattened (the new model has no parent)
  Product                -> catalog.Product (units: kg/l/piece -> kg/litr/dona)
  PriceEntry             -> reports.PriceReport; flagged entries stay FLAGGED, the rest become CONFIRMED
  PriceConfirmation      -> reports.Confirmation with weight 1
  PriceAlert             -> market.PriceAlert (matched by product name)
  Profile.shop_name      -> accounts.UserProfile.shop_name (only when still empty)
  Profile.phone          -> accounts.UserProfile.phone when it is a valid, unused Uzbek number

What is not carried over: the category emoji and DailyPriceStat (rebuilt from reports). Product and category images, product description and usage
are copied; on a product that already exists only empty fields are filled.
"""
from collections import Counter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import UserProfile
from apps.accounts.phone import normalize_phone
from apps.catalog.models import Category, City, Place, Product

from apps.market.models import PriceAlert

from .models import Confirmation, PriceReport

UNIT = {"kg": "kg", "g": "g", "l": "litr", "ml": "ml", "piece": "dona"}
BASE_UNIT = {"kg": "kg", "l": "litr", "piece": "dona"}


class _Rollback(Exception):
    pass


def _category(legacy, stats):
    row = Category.objects.filter(slug=legacy.slug).first() or Category.objects.filter(name=legacy.name).first()
    if row is None:
        row = Category.objects.create(name=legacy.name, slug=legacy.slug, sort_order=legacy.sort_order,
                                      image=legacy.image.name or None)
        stats["categories_created"] += 1
    elif legacy.image and not row.image:
        row.image = legacy.image.name
        row.save(update_fields=["image"])
    return row


def _product(legacy, categories, stats):
    """The new Product for a legacy one, or None when an existing product has a different unit."""
    unit = BASE_UNIT[legacy.base_unit]
    row = Product.objects.filter(name=legacy.name).first()
    if row is None:
        row = Product.objects.create(name=legacy.name, category=categories[legacy.category_id],
                                     default_unit=unit, is_active=legacy.is_active, description=legacy.description,
                                     usage=legacy.usage, image=legacy.image.name or None)
        stats["products_created"] += 1
    elif row.default_unit != unit:
        stats["products_unit_conflict"] += 1
        return None
    else:
        # Product already exists (e.g. from seed_namangan): fill only what is still empty, never overwrite.
        changed = []
        for field in ("description", "usage"):
            if getattr(legacy, field) and not getattr(row, field):
                setattr(row, field, getattr(legacy, field))
                changed.append(field)
        if legacy.image and not row.image:
            row.image = legacy.image.name
            changed.append("image")
        if changed:
            row.save(update_fields=changed)
            stats["products_enriched"] += 1
    return row


def _city(region_name, forced_slug):
    if forced_slug:
        return City.objects.get(slug=forced_slug)
    slug = slugify(region_name) or "shahar"
    row = City.objects.filter(slug=slug).first() or City.objects.filter(name=region_name).first()
    return row or City.objects.create(name=region_name, slug=slug)


def _place_name(loc, name_counts):
    """Legacy names are not unique; the new model needs (city, name) unique. Deterministic, so reruns match."""
    if name_counts[(loc.district.region_id, loc.name)] > 1:
        return f"{loc.name} ({loc.district.name})"
    return loc.name


def _place(loc, name_counts, forced_slug, stats):
    city = _city(loc.district.region.name, forced_slug)
    name = _place_name(loc, name_counts)
    row = Place.objects.filter(city=city, name=name).first()
    if row is None:
        address = ", ".join(p for p in (loc.district.name, loc.address) if p)
        row = Place.objects.create(name=name, type=loc.type, city=city, address=address[:255], lat=loc.lat,
                                   lng=loc.lng, website=loc.website, is_active=loc.is_active)
        stats["places_created"] += 1
    return row


def _run(city_slug):
    from prices.models import Category as LCategory, Location, PriceConfirmation, PriceEntry, Product as LProduct
    from prices.models import PriceAlert as LAlert, Profile

    stats = Counter()

    categories = {c.pk: _category(c, stats) for c in LCategory.objects.all()}
    products = {p.pk: _product(p, categories, stats) for p in LProduct.objects.all()}

    locations = list(Location.objects.select_related("district__region"))
    name_counts = Counter((loc.district.region_id, loc.name) for loc in locations)
    places = {loc.pk: _place(loc, name_counts, city_slug, stats) for loc in locations}

    reports = {}  # legacy entry id -> PriceReport
    entries = PriceEntry.objects.select_related("user").order_by("id")
    for e in entries:
        product, place = products.get(e.product_id), places.get(e.location_id)
        if product is None:
            stats["reports_skipped_unit_conflict"] += 1
            continue
        price = int(e.price)
        found = PriceReport.objects.filter(product=product, place=place, user=e.user,
                                           created_at=e.created_at, price=price).first()
        if found:
            reports[e.pk] = found
            stats["reports_existing"] += 1
            continue
        report = PriceReport(
            product=product, place=place, user=e.user, price=price, quantity=e.quantity, unit=UNIT[e.unit],
            is_promo=e.is_promo, old_price=int(e.old_price) if e.old_price is not None else None,
            source_url=e.source_url, created_at=e.created_at,
            status=PriceReport.Status.FLAGGED if e.is_flagged else PriceReport.Status.CONFIRMED,
        )
        if e.photo:
            report.photo = e.photo.name
        try:
            with transaction.atomic():
                report.save()
        except ValidationError:
            stats["reports_failed"] += 1
            continue
        reports[e.pk] = report
        stats["reports_created"] += 1

    for c in PriceConfirmation.objects.all():
        report = reports.get(c.entry_id)
        if report is None:
            continue
        _, created = Confirmation.objects.get_or_create(report=report, user_id=c.user_id,
                                                        defaults={"created_at": c.created_at})
        stats["confirmations_created"] += int(created)

    for a in LAlert.objects.select_related("product"):
        product = products.get(a.product_id)
        if product is None:
            stats["alerts_skipped"] += 1
            continue
        alert, created = PriceAlert.objects.get_or_create(
            user_id=a.user_id, product=product,
            defaults={"target_price": int(a.target_price), "is_active": a.is_active, "triggered_at": a.triggered_at,
                      "last_notified_price": a.last_notified_price})
        if created:
            PriceAlert.objects.filter(pk=alert.pk).update(created_at=a.created_at)  # auto_now_add ignores input
        stats["alerts_created" if created else "alerts_existing"] += 1

    for p in Profile.objects.select_related("user"):
        profile, _ = UserProfile.objects.get_or_create(user=p.user)
        if p.shop_name and not profile.shop_name:
            profile.shop_name = p.shop_name
            profile.save(update_fields=["shop_name"])
            stats["shop_names_copied"] += 1
        if not p.phone:
            continue
        try:
            phone = normalize_phone(p.phone)
        except ValueError:
            stats["phones_invalid"] += 1
            continue
        if profile.phone:
            continue
        if UserProfile.objects.filter(phone=phone).exists():
            stats["phones_duplicate"] += 1
            continue
        profile.phone = phone
        profile.save(update_fields=["phone"])
        stats["phones_copied"] += 1

    return stats


def import_legacy(*, city_slug=None, dry_run=False):
    """Copy legacy data. Returns a Counter of what happened. With dry_run nothing is kept."""
    result = {}
    try:
        with transaction.atomic():
            result["stats"] = _run(city_slug)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return result["stats"]
