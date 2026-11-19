"""Verification rules for price reports. Pure domain logic: no HTTP, no templates.

Rules (numbers live in constants.py):
  1. Reporter farther than MAX_DISTANCE_M from the place (or sending no location): the report is
     accepted but earns no points and its author's trust counts for less (FAR_TRUST_FACTOR).
  2. Anomaly filter: more than +-40% from the 14-day median of the same product + city -> "flagged".
  3. Confirmed by enough independent confirmations, or by 1 confirmation + a photo.
  4. The higher the author's trust, the less confirmation weight is required; each confirmer's weight
     grows with the confirmer's own trust.
  5. One report per user + place + product per 6 hours.
  6. Others' prices are revealed only as the *result of submitting* (SubmitResult.context); nothing in
     this module lets the add-price form read them beforehand.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.reports.models import Confirmation, PriceReport
from apps.reports.units import compute_normalized_price

from . import constants as C
from .errors import AlreadyConfirmed, RateLimited, ReportClosed, SelfConfirmation

Status = PriceReport.Status
_TWO_PLACES = Decimal("0.01")


# ----------------------------------------------------------------------------- rule 1: distance
def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(a))


def assess_distance(place, reporter_lat, reporter_lng):
    """-> (distance_m or None, is_far).
    No reporter location: cannot prove presence -> far. Place without coordinates: cannot judge -> not far
    (an admin data gap must not punish every reporter)."""
    if reporter_lat is None or reporter_lng is None:
        return None, True
    if place.lat is None or place.lng is None:
        return None, False
    distance = round(haversine_m(reporter_lat, reporter_lng, place.lat, place.lng))
    return distance, distance > C.MAX_DISTANCE_M


# ----------------------------------------------------------------------------- rule 2: anomaly
def is_anomalous(product, city_id, normalized_price, now=None):
    """True when normalized_price deviates more than 40% from the 14-day median of comparable reports
    (same product, same city, not rejected, not flagged). Needs >= ANOMALY_MIN_SAMPLES to judge."""
    now = now or timezone.now()
    values = list(
        PriceReport.objects.filter(
            product=product, place__city_id=city_id,
            created_at__gte=now - timedelta(days=C.ANOMALY_WINDOW_DAYS), created_at__lte=now,
            status__in=[Status.PENDING, Status.CONFIRMED],
        ).values_list("normalized_price", flat=True)
    )
    if len(values) < C.ANOMALY_MIN_SAMPLES:
        return False
    median = statistics.median(values)
    if median <= 0:
        return False
    return abs(Decimal(normalized_price) - median) / median > C.ANOMALY_MAX_DEVIATION


# ----------------------------------------------------------------------------- rule 5: rate limit
def check_rate_limit(user, place, product, now=None):
    now = now or timezone.now()
    window = timedelta(hours=C.RATE_LIMIT_HOURS)
    last = (PriceReport.objects.filter(user=user, place=place, product=product, created_at__gt=now - window)
            .order_by("-created_at").values_list("created_at", flat=True).first())
    if last is not None:
        raise RateLimited(retry_after=last + window - now)


# ----------------------------------------------------------------------------- trust, points, badges
def confirmer_weight(trust_score):
    raw = Decimal(trust_score) / C.WEIGHT_TRUST_DIVISOR
    return max(C.WEIGHT_MIN, min(C.WEIGHT_MAX, raw)).quantize(_TWO_PLACES)


def effective_author_trust(report, author_trust):
    """Rule 1 + 4: a far report's author counts as less trustworthy for the threshold discount."""
    return Decimal(author_trust) * (C.FAR_TRUST_FACTOR if report.is_far else 1)


def required_weight(report, author_trust):
    """Total confirmer weight a *pending* report needs (rule 4)."""
    trust = effective_author_trust(report, author_trust)
    if trust >= C.TRUST_EXPERT:
        return C.CONFIRM_THRESHOLD_EXPERT
    if trust >= C.TRUST_TRUSTED:
        return C.CONFIRM_THRESHOLD_TRUSTED
    return C.CONFIRM_THRESHOLD


def badge_for(trust_score, points):
    B = UserProfile.Badge
    if trust_score >= C.BADGE_EXPERT_TRUST and points >= C.BADGE_EXPERT_POINTS:
        return B.EXPERT
    if trust_score >= C.BADGE_TRUSTED_TRUST and points >= C.BADGE_TRUSTED_POINTS:
        return B.TRUSTED
    if points >= C.BADGE_REGULAR_POINTS:
        return B.REGULAR
    return B.NEWCOMER


def _locked_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return UserProfile.objects.select_for_update().get(pk=profile.pk)  # row lock serialises per-user changes


def _bump_points(user_id, points):
    """Lock-free point award (atomic F() update). Used for confirmers so two users confirming each other's
    reports at the same time can never deadlock on profile rows."""
    UserProfile.objects.filter(user_id=user_id).update(points=F("points") + points)
    profile = UserProfile.objects.get(user_id=user_id)
    badge = badge_for(profile.trust_score, profile.points)
    if badge != profile.badge:
        UserProfile.objects.filter(pk=profile.pk).update(badge=badge)


def _apply(profile, points=0, trust=0):
    profile.points += points
    profile.trust_score = max(C.TRUST_MIN, min(C.TRUST_MAX, profile.trust_score + trust))
    profile.badge = badge_for(profile.trust_score, profile.points)
    profile.save(update_fields=["points", "trust_score", "badge"])


# ----------------------------------------------------------------------------- rule 6: reveal after submit
def price_context(report, now=None):
    """What other people reported for the same product, shown ONLY after the reporter has submitted.
    Confirmed reports of the last week in the same city, own report excluded."""
    now = now or timezone.now()
    values = list(
        PriceReport.objects.filter(
            product=report.product, place__city_id=report.place.city_id, status=Status.CONFIRMED,
            created_at__gte=now - timedelta(days=C.CONTEXT_WINDOW_DAYS), created_at__lte=now,
        ).exclude(pk=report.pk).values_list("normalized_price", flat=True)
    )
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None, "yours_vs_median_pct": None}
    median = Decimal(statistics.median(values)).quantize(_TWO_PLACES)
    diff = ((report.normalized_price - median) / median * 100).quantize(_TWO_PLACES) if median else None
    return {"count": len(values), "median": median, "min": min(values), "max": max(values),
            "yours_vs_median_pct": diff}


# ----------------------------------------------------------------------------- submit / confirm / reject
@dataclass
class SubmitResult:
    report: PriceReport
    context: dict = field(default_factory=dict)


@transaction.atomic
def submit_report(*, user, product, place, price, unit, quantity=Decimal("1"), photo=None,
                  reporter_lat=None, reporter_lng=None, now=None):
    """Create a report applying rules 1, 2 and 5. Raises RateLimited, or Django ValidationError for a bad unit."""
    now = now or timezone.now()
    profile = _locked_profile(user)
    check_rate_limit(user, place, product, now)

    normalized = compute_normalized_price(product, price, quantity, unit)  # validates unit/quantity early
    distance_m, is_far = assess_distance(place, reporter_lat, reporter_lng)
    flagged = is_anomalous(product, place.city_id, normalized, now)  # computed BEFORE the report exists

    report = PriceReport.objects.create(
        product=product, place=place, user=user, price=price, quantity=quantity, unit=unit, photo=photo,
        reporter_lat=reporter_lat, reporter_lng=reporter_lng, is_far=is_far, distance_m=distance_m,
        status=Status.FLAGGED if flagged else Status.PENDING, created_at=now,
        status_changed_at=now if flagged else None,
    )
    if not is_far:
        report.points_awarded = C.POINTS_PER_REPORT
        report.save(update_fields=["points_awarded"])
        _apply(profile, points=C.POINTS_PER_REPORT)
    return SubmitResult(report=report, context=price_context(report, now))


@dataclass
class ConfirmResult:
    confirmation: Confirmation
    report: PriceReport
    became_confirmed: bool


@transaction.atomic
def confirm_report(report, user, now=None):
    """Record one user's confirmation (once) and re-evaluate the report (rules 3 and 4)."""
    now = now or timezone.now()
    report = PriceReport.objects.select_for_update().select_related("user").get(pk=report.pk)
    if report.status == Status.REJECTED:
        raise ReportClosed()
    if report.user_id == user.id:
        raise SelfConfirmation()

    confirmer, _created = UserProfile.objects.get_or_create(user=user)  # read-only: weight comes from trust
    try:
        with transaction.atomic():
            confirmation = Confirmation.objects.create(
                report=report, user=user, weight=confirmer_weight(confirmer.trust_score), created_at=now)
    except IntegrityError:
        raise AlreadyConfirmed()

    was_open = report.status in (Status.PENDING, Status.FLAGGED)
    if was_open:
        _bump_points(user.id, C.POINTS_PER_CONFIRMATION)  # no point farming on already-settled reports
    became = evaluate_report(report, now) if was_open else False
    return ConfirmResult(confirmation=confirmation, report=report, became_confirmed=became)


def evaluate_report(report, now=None):
    """Decide whether an open report is now confirmed. Returns True when it just became confirmed."""
    if report.status not in (Status.PENDING, Status.FLAGGED):
        return False
    stats = report.confirmations.aggregate(total=Sum("weight"))
    total = stats["total"] or Decimal("0")
    count = report.confirmations.count()

    if report.status == Status.FLAGGED:
        ok = total >= C.FLAGGED_CONFIRM_THRESHOLD
    else:
        author = UserProfile.objects.get_or_create(user_id=report.user_id)[0]
        ok = total >= required_weight(report, author.trust_score) or (
            bool(report.photo) and count >= C.PHOTO_MIN_CONFIRMATIONS)
    if ok:
        mark_confirmed(report, now)
    return ok


@transaction.atomic
def mark_confirmed(report, now=None):
    """Confirm a report and reward its author. Idempotent. Also used by admin actions."""
    if report.status == Status.CONFIRMED:
        return report
    report.status = Status.CONFIRMED
    report.status_changed_at = now or timezone.now()
    bonus = 0 if report.is_far else C.POINTS_REPORT_CONFIRMED
    report.points_awarded += bonus
    report.save(update_fields=["status", "status_changed_at", "points_awarded"])
    _apply(_locked_profile(report.user),
           points=bonus, trust=C.TRUST_GAIN_CONFIRMED_FAR if report.is_far else C.TRUST_GAIN_CONFIRMED)
    return report


@transaction.atomic
def reject_report(report, now=None):
    """Reject a report and lower its author's trust. Idempotent. Points already granted are kept."""
    if report.status == Status.REJECTED:
        return report
    report.status = Status.REJECTED
    report.status_changed_at = now or timezone.now()
    report.save(update_fields=["status", "status_changed_at"])
    _apply(_locked_profile(report.user), trust=-C.TRUST_LOSS_REJECTED)
    return report


def expire_flagged(now=None):
    """Reject flagged reports nobody vouched for within FLAGGED_EXPIRY_HOURS. Returns how many (Celery, hourly)."""
    now = now or timezone.now()
    stale = PriceReport.objects.filter(
        status=Status.FLAGGED, created_at__lte=now - timedelta(hours=C.FLAGGED_EXPIRY_HOURS))
    count = 0
    for report in stale.select_related("user"):
        reject_report(report, now)
        count += 1
    return count
