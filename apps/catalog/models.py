from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .textnorm import normalize_text


class City(models.Model):
    name = models.CharField(_("Nomi"), max_length=100, unique=True)
    slug = models.SlugField(_("Slug"), max_length=100, unique=True)

    class Meta:
        verbose_name = _("Shahar")
        verbose_name_plural = _("Shaharlar")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(_("Nomi"), max_length=100, unique=True)
    slug = models.SlugField(_("Slug"), max_length=100, unique=True)
    sort_order = models.PositiveSmallIntegerField(_("Tartib raqami"), default=100)

    class Meta:
        verbose_name = _("Kategoriya")
        verbose_name_plural = _("Kategoriyalar")
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        KG = "kg", _("kg")
        PIECE = "dona", _("dona")
        LITER = "litr", _("litr")

    name = models.CharField(_("Nomi"), max_length=150, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products",
                                 verbose_name=_("Kategoriya"))
    default_unit = models.CharField(_("Asosiy birlik"), max_length=10, choices=Unit.choices)
    # Size of one "qop" (sack/pack) expressed in default_unit, e.g. flour: 50 (kg). Null = not sold by pack.
    pack_size = models.DecimalField(_("Qop hajmi (asosiy birlikda)"), max_digits=8, decimal_places=3,
                                    null=True, blank=True)
    is_active = models.BooleanField(_("Faol"), default=True)
    # Normalised name (see textnorm.py); search runs against it. Kept in sync by save().
    search_key = models.CharField(max_length=300, editable=False, default="", blank=True, db_index=True)

    class Meta:
        verbose_name = _("Mahsulot")
        verbose_name_plural = _("Mahsulotlar")
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(pack_size__isnull=True) | models.Q(pack_size__gt=0),
                                   name="product_pack_size_positive"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.search_key = normalize_text(self.name)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "name" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"search_key"}
        super().save(*args, **kwargs)


class ProductAlias(models.Model):
    """Alternative names people search by: "govyadina", "mol go'shti"."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="aliases",
                                verbose_name=_("Mahsulot"))
    alias = models.CharField(_("Muqobil nom"), max_length=150)
    search_key = models.CharField(max_length=300, editable=False, default="", db_index=True)

    class Meta:
        verbose_name = _("Muqobil nom")
        verbose_name_plural = _("Muqobil nomlar")
        constraints = [models.UniqueConstraint(fields=["product", "search_key"], name="uniq_alias_per_product")]

    def __str__(self):
        return self.alias

    def save(self, *args, **kwargs):
        self.search_key = normalize_text(self.alias)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "alias" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"search_key"}
        super().save(*args, **kwargs)


class Place(models.Model):
    class Type(models.TextChoices):
        BAZAAR = "bazaar", _("Bozor")
        SHOP = "shop", _("Do'kon")
        SUPERMARKET = "supermarket", _("Supermarket")

    name = models.CharField(_("Nomi"), max_length=150)
    type = models.CharField(_("Turi"), max_length=12, choices=Type.choices)
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="places", verbose_name=_("Shahar"))
    address = models.CharField(_("Manzil"), max_length=255, blank=True)
    lat = models.DecimalField(_("Kenglik (lat)"), max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(_("Uzunlik (lng)"), max_digits=9, decimal_places=6, null=True, blank=True)
    opens_at = models.TimeField(_("Ochilish vaqti"), null=True, blank=True)
    closes_at = models.TimeField(_("Yopilish vaqti"), null=True, blank=True)
    is_active = models.BooleanField(_("Faol"), default=True)

    class Meta:
        verbose_name = _("Joy")
        verbose_name_plural = _("Joylar")
        ordering = ["city", "name"]
        constraints = [models.UniqueConstraint(fields=["city", "name"], name="uniq_place_name_per_city")]

    def __str__(self):
        return self.name

    def clean(self):
        if (self.lat is None) != (self.lng is None):
            raise ValidationError(_("Kenglik va uzunlik birga kiritilishi kerak."))
        if self.lat is not None and not (-90 <= self.lat <= 90 and -180 <= self.lng <= 180):
            raise ValidationError(_("Koordinatalar noto'g'ri."))
