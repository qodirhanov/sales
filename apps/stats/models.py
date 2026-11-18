from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import City, Place, Product


class ProductStats(models.Model):
    """Hourly cache (filled by a Celery task, added in the API stage). Two kinds of rows:
    - place is NULL  -> city aggregate for (product, city): average, cheapest place, change, 6-week chart
    - place is set   -> current price at that place (median of confirmed reports, last 7 days)
    All prices are per ONE product.default_unit."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stats", verbose_name=_("Mahsulot"))
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="product_stats", verbose_name=_("Shahar"))
    place = models.ForeignKey(Place, on_delete=models.CASCADE, null=True, blank=True, related_name="product_stats",
                              verbose_name=_("Joy"))

    current_price = models.DecimalField(_("Joriy narx (median)"), max_digits=12, decimal_places=2, null=True, blank=True)
    city_avg = models.DecimalField(_("Shahar o'rtachasi"), max_digits=12, decimal_places=2, null=True, blank=True)
    cheapest_place = models.ForeignKey(Place, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                       verbose_name=_("Eng arzon joy"))
    week_change_pct = models.DecimalField(_("Haftalik o'zgarish (%)"), max_digits=7, decimal_places=2,
                                          null=True, blank=True)
    # Oldest -> newest, 6 entries: [{"week_start": "2026-10-12", "median": "8200.00"}, ...] ("median" may be null).
    weekly_medians = models.JSONField(_("Haftalik medianlar"), default=list, blank=True)
    sample_count = models.PositiveIntegerField(_("Namunalar soni"), default=0)
    computed_at = models.DateTimeField(_("Hisoblangan vaqt"), auto_now=True)

    class Meta:
        verbose_name = _("Mahsulot statistikasi")
        verbose_name_plural = _("Mahsulot statistikasi")
        constraints = [
            models.UniqueConstraint(fields=["product", "city", "place"], name="uniq_stats_product_city_place",
                                    condition=models.Q(place__isnull=False)),
            models.UniqueConstraint(fields=["product", "city"], name="uniq_stats_product_city",
                                    condition=models.Q(place__isnull=True)),
        ]

    def __str__(self):
        return f"{self.product} / {self.place or self.city}: {self.current_price or self.city_avg}"


class ReferencePrice(models.Model):
    """Official min-max prices (e.g. stat.uz farmers' markets). Not user reports: no place, no author."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reference_prices",
                                verbose_name=_("Mahsulot"))
    region = models.CharField(_("Hudud"), max_length=100, blank=True)
    date = models.DateField(_("Sana"))
    min_price = models.PositiveIntegerField(_("Eng past narx"))
    max_price = models.PositiveIntegerField(_("Eng yuqori narx"))
    source = models.CharField(_("Manba"), max_length=50, default="stat.uz")

    class Meta:
        verbose_name = _("Rasmiy narx")
        verbose_name_plural = _("Rasmiy narxlar")
        ordering = ["-date", "product"]
        constraints = [
            models.UniqueConstraint(fields=["product", "region", "date", "source"], name="uniq_reference_price"),
            models.CheckConstraint(condition=models.Q(min_price__lte=models.F("max_price")),
                                   name="reference_min_lte_max"),
        ]

    def __str__(self):
        return f"{self.product} {self.date}: {self.min_price}-{self.max_price}"
