from rest_framework.throttling import ScopedRateThrottle


class PriceCreateThrottle(ScopedRateThrottle):
    """Scope 'price_create' (see REST_FRAMEWORK rates), applied to POST only."""

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class ConfirmThrottle(ScopedRateThrottle):
    """Limits POST /prices/<id>/confirm/ per user (scope 'price_confirm')."""
