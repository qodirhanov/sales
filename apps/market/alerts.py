"""Price alerts on the new models: the API (/api/v2/alerts/) and the delivery logic behind `check_alerts`."""
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import mixins, permissions, serializers, viewsets

from apps.catalog.models import Product

from . import selectors as sel
from .models import PriceAlert

BASE_UNIT_OUT = {"kg": "kg", "litr": "l", "dona": "piece"}


def alert_is_due(alert, best):
    """Fire when best <= target and it is new (never notified) or cheaper than the last notification."""
    if best is None or best > alert.target_price:
        return False
    return alert.last_notified_price is None or best < alert.last_notified_price


class PriceAlertSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    product_name = serializers.CharField(source="product.name", read_only=True)
    base_unit = serializers.SerializerMethodField()
    current_best = serializers.SerializerMethodField()
    is_reached = serializers.SerializerMethodField()

    class Meta:
        model = PriceAlert
        fields = ("id", "product", "product_name", "base_unit", "target_price", "is_active",
                  "current_best", "is_reached", "triggered_at", "created_at")
        read_only_fields = ("id", "triggered_at", "created_at")

    def validate_target_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Target price must be positive.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        product = attrs.get("product")
        if self.instance is None and request and product and \
                PriceAlert.objects.filter(user=request.user, product=product).exists():
            raise serializers.ValidationError({"product": "Bu mahsulot uchun ogohlantirish allaqachon bor."})
        return attrs

    def get_base_unit(self, obj):
        return BASE_UNIT_OUT[obj.product.default_unit]

    def _best(self, obj):
        cache = self.context.setdefault("_best_cache", {})
        if obj.product_id not in cache:
            cache[obj.product_id] = sel.best_current_price(obj.product)
        return cache[obj.product_id]

    def get_current_best(self, obj):
        return self._best(obj)

    def get_is_reached(self, obj):
        best = self._best(obj)
        return best is not None and best <= obj.target_price


class PriceAlertViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
                        mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """The caller's own alerts."""
    serializer_class = PriceAlertSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user).select_related("product")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


def fire_due_alerts():
    """Check every active alert, notify the ones whose target was reached. Returns how many fired."""
    fired = 0
    alerts = PriceAlert.objects.filter(is_active=True, product__is_active=True).select_related("user", "product")
    best_cache = {}
    for alert in alerts:
        if alert.product_id not in best_cache:
            best_cache[alert.product_id] = sel.best_current_price(alert.product)
        best = best_cache[alert.product_id]
        if best is not None and best > alert.target_price and alert.last_notified_price is not None:
            # Price went back up: re-arm so the next drop notifies again.
            alert.last_notified_price = None
            alert.save(update_fields=["last_notified_price"])
            continue
        if not alert_is_due(alert, best):
            continue
        if alert.user.email:
            send_mail(
                subject=f"Narx tushdi: {alert.product.name}",
                message=(f"{alert.product.name} narxi {best} so'm / {alert.product.get_default_unit_display()} "
                         f"ga tushdi (maqsadingiz: {alert.target_price} so'm)."),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[alert.user.email],
                fail_silently=True,
            )
        alert.triggered_at = timezone.now()
        alert.last_notified_price = best
        alert.save(update_fields=["triggered_at", "last_notified_price"])
        fired += 1
    return fired
