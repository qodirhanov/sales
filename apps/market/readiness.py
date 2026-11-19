"""Is the database ready to run with USE_NEW_API=True? Read-only checks, used by `check_new_api_ready`.

Each check returns (level, message): "ok", "warn" (works, but you will want to fix it) or "fail"
(turning the flag on would lose or hide data).
"""
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.accounts.models import UserProfile
from apps.catalog.models import City, Place, Product
from apps.reports.models import PriceReport


def run_checks():
    from prices.models import PriceEntry, Product as LegacyProduct

    checks = []
    add = lambda level, msg: checks.append((level, msg))

    legacy_entries = PriceEntry.objects.count()
    new_reports = PriceReport.objects.count()
    if legacy_entries and not new_reports:
        add("fail", f"{legacy_entries} legacy prices but no new reports: run import_legacy_prices first.")
    elif legacy_entries > new_reports:
        add("warn", f"{legacy_entries} legacy prices vs {new_reports} new reports: some were skipped or are new "
                    "since the last import. Re-run import_legacy_prices (safe to repeat) and read its counters.")
    else:
        add("ok", f"{new_reports} new reports cover the {legacy_entries} legacy prices.")

    names = set(Product.objects.values_list("name", flat=True))
    missing = [n for n in LegacyProduct.objects.values_list("name", flat=True) if n not in names]
    add("fail" if missing else "ok",
        f"{len(missing)} legacy products are missing in the new catalog, e.g. {missing[:3]}." if missing
        else "Every legacy product exists in the new catalog.")

    if not City.objects.exists():
        add("fail", "No city yet: run seed_namangan (or create one in the admin).")
    places = Place.objects.filter(is_active=True)
    no_coords = places.filter(lat__isnull=True) | places.filter(lng__isnull=True)
    if not places.exists():
        add("fail", "No active places: nobody can add a price.")
    elif no_coords.exists():
        add("warn", f"{no_coords.count()} of {places.count()} active places have no coordinates. For them the "
                    "500 m rule cannot be checked, so every reporter counts as present. Set lat/lng in the admin.")
    else:
        add("ok", "All active places have coordinates (the 500 m rule works everywhere).")

    users = get_user_model().objects.count()
    profiles = UserProfile.objects.count()
    add("ok" if profiles >= users else "warn",
        f"{profiles} reputation profiles for {users} users." if profiles >= users
        else f"{users - profiles} users have no reputation profile yet (created on first use, harmless).")

    add("ok" if settings.USE_NEW_API else "warn",
        "USE_NEW_API is ON." if settings.USE_NEW_API else "USE_NEW_API is off: set USE_NEW_API=True to switch.")
    return checks
