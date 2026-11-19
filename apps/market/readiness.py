"""Is the database ready for production use? Read-only checks, used by `check_setup`.

Each check returns (level, message): "ok", "warn" (works, but you will want to fix it) or "fail".
"""
from django.contrib.auth import get_user_model

from apps.accounts.models import UserProfile
from apps.catalog.models import City, Place, Product
from apps.reports.models import PriceReport

from .models import PriceAlert


def run_checks():
    checks = []
    add = lambda level, msg: checks.append((level, msg))

    if not City.objects.exists():
        add("fail", "No city yet: run seed_namangan (or create one in the admin).")
    if not Product.objects.filter(is_active=True).exists():
        add("fail", "No active products: run seed_namangan (or add products in the admin).")

    places = Place.objects.filter(is_active=True)
    no_coords = places.filter(lat__isnull=True) | places.filter(lng__isnull=True)
    if not places.exists():
        add("fail", "No active places: nobody can add a price.")
    elif no_coords.exists():
        add("warn", f"{no_coords.count()} of {places.count()} active places have no coordinates. For them the "
                    "500 m rule cannot be checked, so every reporter counts as present. Set lat/lng in the admin.")
    else:
        add("ok", "All active places have coordinates (the 500 m rule works everywhere).")

    reports = PriceReport.objects.count()
    add("ok" if reports else "warn",
        f"{reports} price reports." if reports else "No price reports yet: the site will look empty until people add some.")

    add("ok", f"{PriceAlert.objects.count()} price alerts (schedule `check_alerts` to deliver them).")

    users = get_user_model().objects.count()
    profiles = UserProfile.objects.count()
    add("ok" if profiles >= users else "warn",
        f"{profiles} reputation profiles for {users} users." if profiles >= users
        else f"{users - profiles} users have no reputation profile yet (created on first use, harmless).")
    return checks
