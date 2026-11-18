from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Place, Product

from .units import compute_normalized_price


class PriceReport(models.Model):
    class Unit(models.TextChoices):
        KG = "kg", _("kg")
        G = "g", _("g")
        LITER = "litr", _("litr")
        ML = "ml", _("ml")
        PIECE = "dona", _("dona")
        PACK = "qop", _("qop")

    class Status(models.TextChoices):
        PENDING = "pending", _("Kutilmoqda")
        CONFIRMED = "confirmed", _("Tasdiqlangan")
        REJECTED = "rejected", _("Rad etilgan")
        FLAGGED = "flagged", _("Shubhali")

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="reports",
                                verbose_name=_("Mahsulot"))
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name="reports", verbose_name=_("Joy"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="price_reports",
                             verbose_name=_("Foydalanuvchi"))

    price = models.PositiveIntegerField(_("Narx (so'm)"))  # whole so'm, never float
    quantity = models.DecimalField(_("Miqdor"), max_digits=10, decimal_places=3, default=Decimal("1"))
    unit = models.CharField(_("Birlik"), max_length=5, choices=Unit.choices)
    # Price per ONE product.default_unit; computed in save().
    normalized_price = models.DecimalField(_("1 birlik narxi"), max_digits=12, decimal_places=2, editable=False)
    photo = models.ImageField(_("Rasm"), upload_to="report_photos/%Y/%m/", null=True, blank=True)

    reporter_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    reporter_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # Filled by the verification service: reporter was farther than the allowed radius (or sent no location).
    is_far = models.BooleanField(_("Joydan uzoqda"), default=False)
    distance_m = models.PositiveIntegerField(_("Joygacha masofa (m)"), null=True, blank=True)

    status = models.CharField(_("Holat"), max_length=10, choices=Status.choices, default=Status.PENDING)
    points_awarded = models.PositiveSmallIntegerField(_("Berilgan ball"), default=0)
    created_at = models.DateTimeField(_("Kiritilgan vaqt"), default=timezone.now)
    status_changed_at = models.DateTimeField(_("Holat o'zgargan vaqt"), null=True, blank=True)

    class Meta:
        verbose_name = _("Narx xabari")
        verbose_name_plural = _("Narx xabarlari")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["product", "place", "-created_at"], name="rep_prod_place_created"),
            models.Index(fields=["product", "status", "-created_at"], name="rep_prod_status_created"),
            models.Index(fields=["user", "place", "product", "-created_at"], name="rep_user_place_prod"),
            models.Index(fields=["status", "created_at"], name="rep_status_created"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="report_price_positive"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="report_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.product} @ {self.place}: {self.price} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        self.normalized_price = compute_normalized_price(self.product, self.price, self.quantity, self.unit)
        super().save(*args, **kwargs)


class Confirmation(models.Model):
    """One user vouches for one report, once. `weight` is frozen at confirmation time
    (derived from the confirmer's trust), so later trust changes do not rewrite history."""
    report = models.ForeignKey(PriceReport, on_delete=models.CASCADE, related_name="confirmations",
                               verbose_name=_("Xabar"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="confirmations", verbose_name=_("Foydalanuvchi"))
    weight = models.DecimalField(_("Og'irlik"), max_digits=4, decimal_places=2, default=Decimal("1.00"))
    created_at = models.DateTimeField(_("Vaqt"), default=timezone.now)

    class Meta:
        verbose_name = _("Tasdiq")
        verbose_name_plural = _("Tasdiqlar")
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint(fields=["report", "user"], name="reports_uniq_confirmation_per_user")]

    def __str__(self):
        return f"{self.user_id} -> {self.report_id} (x{self.weight})"
