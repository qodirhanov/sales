from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .phone import normalize_phone, validate_phone

DEFAULT_TRUST_SCORE = 50


class UserProfile(models.Model):
    """Per-user reputation data. The stock Django User stays the auth model; the phone number
    lives here and a custom auth backend (added with the API) maps phone -> user."""

    class Badge(models.TextChoices):
        NEWCOMER = "newcomer", _("Yangi")
        REGULAR = "regular", _("Doimiy")
        TRUSTED = "trusted", _("Ishonchli")
        EXPERT = "expert", _("Bozor ustasi")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="userprofile", verbose_name=_("Foydalanuvchi"))
    phone = models.CharField(_("Telefon"), max_length=13, unique=True, null=True, blank=True,
                             validators=[validate_phone])
    shop_name = models.CharField(_("Do'kon / bozor nomi"), max_length=120, blank=True)
    points = models.PositiveIntegerField(_("Ballar"), default=0)
    trust_score = models.PositiveSmallIntegerField(
        _("Ishonch darajasi (0-100)"), default=DEFAULT_TRUST_SCORE, validators=[MaxValueValidator(100)])
    badge = models.CharField(_("Nishon"), max_length=10, choices=Badge.choices, default=Badge.NEWCOMER)
    created_at = models.DateTimeField(_("Yaratilgan"), auto_now_add=True)

    class Meta:
        verbose_name = _("Profil")
        verbose_name_plural = _("Profillar")
        constraints = [
            models.CheckConstraint(condition=models.Q(trust_score__lte=100), name="userprofile_trust_lte_100"),
        ]

    def __str__(self):
        return f"{self.user} ({self.trust_score})"

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone) if self.phone else None  # '' must not collide on unique
        super().save(*args, **kwargs)
