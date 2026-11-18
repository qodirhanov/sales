from rest_framework.throttling import ScopedRateThrottle


class PriceCreateThrottle(ScopedRateThrottle):
    """Applies the 'price_create' scope only to POST (reads are not limited)."""

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class ConfirmThrottle(ScopedRateThrottle):
    """Limits POST /api/prices/<id>/confirm/ per user (scope 'price_confirm')."""
