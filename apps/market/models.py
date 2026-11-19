from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product


class PriceAlert(models.Model):
    """'Tell me when <product> drops to <target_price> so'm per default unit or lower.'
    Delivery is done by `manage.py check_alerts`."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="market_alerts",
                             verbose_name=_("Foydalanuvchi"))
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts", verbose_name=_("Mahsulot"))
    target_price = models.PositiveIntegerField(_("Maqsad narx (1 birlik, so'm)"))
    is_active = models.BooleanField(_("Faol"), default=True)
    triggered_at = models.DateTimeField(_("Oxirgi ogohlantirish"), null=True, blank=True)
    last_notified_price = models.DecimalField(_("Oxirgi xabar narxi"), max_digits=12, decimal_places=2,
                                              null=True, blank=True)
    created_at = models.DateTimeField(_("Yaratilgan"), auto_now_add=True)

    class Meta:
        verbose_name = _("Narx ogohlantirishi")
        verbose_name_plural = _("Narx ogohlantirishlari")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="market_uniq_alert_per_user_product"),
            models.CheckConstraint(condition=models.Q(target_price__gt=0), name="market_alert_target_positive"),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.product_id} <= {self.target_price}"
