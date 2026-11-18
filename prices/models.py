from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from urllib.parse import urlparse


def validate_http_url(value):
    """Only http/https links may be stored (blocks javascript:, data:, ftp: ...)."""
    if value and urlparse(value).scheme.lower() not in ("http", "https"):
        raise ValidationError("Faqat http:// yoki https:// havola ruxsat etiladi.")


class Category(models.Model):
    name = models.CharField("Nomi", max_length=100, unique=True)
    slug = models.SlugField("Slug", max_length=100, unique=True)
    emoji = models.CharField("Emoji (ikonka)", max_length=8, blank=True)
    image = models.ImageField("Rasm", upload_to="categories/", null=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children", verbose_name="Asosiy kategoriya")
    sort_order = models.PositiveSmallIntegerField("Tartib raqami", default=100)

    class Meta:
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        """Two levels at most: a parent must itself be top-level; a parent-with-children cannot get a parent."""
        super().clean()
        if self.parent_id is None:
            return
        if self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "Kategoriya o'zining asosiy kategoriyasi bo'la olmaydi."})
        if self.parent.parent_id is not None:
            raise ValidationError({"parent": "Ichma-ich daraja ruxsat etilmagan: asosiy kategoriya o'zi quyi kategoriya bo'lmasligi kerak."})
        if self.pk and self.children.exists():
            raise ValidationError({"parent": "Quyi kategoriyalari bor kategoriyaga asosiy kategoriya berib bo'lmaydi."})


class Product(models.Model):
    class Unit(models.TextChoices):
        KG = "kg", "kg"
        L = "l", "l"
        PIECE = "piece", "dona"

    name = models.CharField("Nomi", max_length=150, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products",
                                 verbose_name="Kategoriya")
    base_unit = models.CharField("Asosiy birlik", max_length=10, choices=Unit.choices)
    is_active = models.BooleanField("Faol", default=True)
    image = models.ImageField("Rasm", upload_to="products/", null=True, blank=True)
    description = models.TextField("Tavsif", blank=True)
    usage = models.TextField("Nima uchun ishlatiladi", blank=True)
    # Normalised name (see textnorm.py) that search runs against; kept in sync by save().
    search_key = models.CharField(max_length=300, editable=False, default="", blank=True)

    class Meta:
        verbose_name = "Mahsulot"
        verbose_name_plural = "Mahsulotlar"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.base_unit})"

    def save(self, *args, **kwargs):
        from .textnorm import normalize_text

        self.search_key = normalize_text(self.name)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "name" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"search_key"}
        super().save(*args, **kwargs)


class Region(models.Model):
    name = models.CharField("Nomi", max_length=100, unique=True)

    class Meta:
        verbose_name = "Viloyat"
        verbose_name_plural = "Viloyatlar"
        ordering = ["name"]

    def __str__(self):
        return self.name


class District(models.Model):
    name = models.CharField("Nomi", max_length=100)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="districts",
                               verbose_name="Viloyat")

    class Meta:
        verbose_name = "Tuman"
        verbose_name_plural = "Tumanlar"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["region", "name"], name="uniq_district_per_region"),
        ]

    def __str__(self):
        return f"{self.name}, {self.region.name}"


class Location(models.Model):
    class Type(models.TextChoices):
        BAZAAR = "bazaar", "Bozor"
        SHOP = "shop", "Do'kon"

    name = models.CharField("Nomi", max_length=150)
    type = models.CharField("Turi", max_length=10, choices=Type.choices)
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="locations",
                                 verbose_name="Tuman")
    address = models.CharField("Manzil", max_length=255, blank=True)
    lat = models.DecimalField("Kenglik (lat)", max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField("Uzunlik (lng)", max_digits=9, decimal_places=6, null=True, blank=True)
    website = models.URLField("Sayt", max_length=500, blank=True, validators=[validate_http_url])
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        verbose_name = "Bozor / do'kon"
        verbose_name_plural = "Bozor va do'konlar"
        ordering = ["name"]

    def __str__(self):
        return self.name


# unit -> (base unit it belongs to, multiplier to convert into that base unit)
UNIT_TO_BASE = {
    "kg": ("kg", Decimal("1")),
    "g": ("kg", Decimal("0.001")),
    "l": ("l", Decimal("1")),
    "ml": ("l", Decimal("0.001")),
    "piece": ("piece", Decimal("1")),
}


def compute_normalized_price(product, price, quantity, unit):
    """Price per one base unit of `product`. Raises ValidationError on bad input."""
    if unit not in UNIT_TO_BASE:
        raise ValidationError({"unit": f"Unknown unit '{unit}'."})
    base, factor = UNIT_TO_BASE[unit]
    if base != product.base_unit:
        raise ValidationError(
            {"unit": f"Unit '{unit}' is incompatible with product base unit '{product.base_unit}'."}
        )
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError({"quantity": "Quantity must be greater than zero."})
    base_qty = quantity * factor
    return (Decimal(price) / base_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class PriceEntry(models.Model):
    class Unit(models.TextChoices):
        KG = "kg", "kg"
        G = "g", "g"
        L = "l", "l"
        ML = "ml", "ml"
        PIECE = "piece", "dona"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="entries",
                                verbose_name="Mahsulot")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="entries",
                                 verbose_name="Bozor / do'kon")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="price_entries",
                             verbose_name="Foydalanuvchi")
    # Whole so'm, never float.
    price = models.DecimalField("Narx (so'm)", max_digits=12, decimal_places=0)
    quantity = models.DecimalField("Miqdor", max_digits=10, decimal_places=3, default=Decimal("1"))
    unit = models.CharField("Birlik", max_length=10, choices=Unit.choices)
    # Price per product.base_unit; computed in save().
    normalized_price = models.DecimalField("1 birlik narxi", max_digits=12, decimal_places=2, editable=False)
    photo = models.ImageField("Rasm", upload_to="price_photos/%Y/%m/", null=True, blank=True)
    old_price = models.DecimalField("Eski narx (aksiyadan oldin)", max_digits=12, decimal_places=0,
                                    null=True, blank=True)
    is_promo = models.BooleanField("Aksiya", default=False)
    source_url = models.URLField("Mahsulot havolasi", max_length=500, blank=True,
                                 validators=[validate_http_url])
    is_flagged = models.BooleanField("Shubhali", default=False)
    created_at = models.DateTimeField("Kiritilgan vaqt", default=timezone.now, db_index=False)

    class Meta:
        verbose_name = "Narx"
        verbose_name_plural = "Narxlar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "location", "-created_at"], name="pe_prod_loc_created"),
            models.Index(fields=["product", "-created_at"], name="pe_prod_created"),
        ]

    def __str__(self):
        return f"{self.product.name} @ {self.location.name}: {self.price} / {self.quantity} {self.unit}"

    def save(self, *args, **kwargs):
        from .services import flag_if_outlier

        self.normalized_price = compute_normalized_price(
            self.product, self.price, self.quantity, self.unit
        )
        if self._state.adding:
            flag_if_outlier(self)
        super().save(*args, **kwargs)


class DailyPriceStat(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="daily_stats",
                                verbose_name="Mahsulot")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="daily_stats",
                                 verbose_name="Bozor / do'kon")
    date = models.DateField("Sana")
    min_price = models.DecimalField("Eng past narx", max_digits=12, decimal_places=2)
    max_price = models.DecimalField("Eng yuqori narx", max_digits=12, decimal_places=2)
    median_price = models.DecimalField("Median narx", max_digits=12, decimal_places=2)
    count = models.PositiveIntegerField("Narxlar soni")

    class Meta:
        verbose_name = "Kunlik statistika"
        verbose_name_plural = "Kunlik statistika"
        unique_together = [("product", "location", "date")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.product_id}/{self.location_id} {self.date}: {self.median_price}"


class Profile(models.Model):
    """Role flag + seller details. Everyone is a buyer by default; sellers may add prices."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
                                verbose_name="Foydalanuvchi")
    is_seller = models.BooleanField("Sotuvchi", default=False)
    shop_name = models.CharField("Do'kon / bozor nomi", max_length=120, blank=True)
    phone = models.CharField("Telefon", max_length=20, blank=True)
    created_at = models.DateTimeField("Yaratilgan vaqt", auto_now_add=True)

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profillar"

    def __str__(self):
        return f"{self.user} ({'sotuvchi' if self.is_seller else 'xaridor'})"


class PriceConfirmation(models.Model):
    """A user vouches that a price is real. Enough confirmations un-flag a suspicious entry."""
    entry = models.ForeignKey(PriceEntry, on_delete=models.CASCADE, related_name="confirmations",
                              verbose_name="Narx")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="price_confirmations", verbose_name="Foydalanuvchi")
    created_at = models.DateTimeField("Vaqt", auto_now_add=True)

    class Meta:
        verbose_name = "Narx tasdig'i"
        verbose_name_plural = "Narx tasdiqlari"
        constraints = [models.UniqueConstraint(fields=["entry", "user"], name="uniq_confirmation_per_user")]

    def __str__(self):
        return f"{self.user_id} -> {self.entry_id}"


class PriceAlert(models.Model):
    """'Tell me when <product> drops to <target_price> so'm per base unit or lower.'"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="price_alerts",
                             verbose_name="Foydalanuvchi")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts",
                                verbose_name="Mahsulot")
    target_price = models.DecimalField("Maqsad narx (1 birlik, so'm)", max_digits=12, decimal_places=0)
    is_active = models.BooleanField("Faol", default=True)
    triggered_at = models.DateTimeField("Oxirgi ogohlantirish", null=True, blank=True)
    last_notified_price = models.DecimalField("Oxirgi xabar narxi", max_digits=12, decimal_places=2,
                                              null=True, blank=True)
    created_at = models.DateTimeField("Yaratilgan", auto_now_add=True)

    class Meta:
        verbose_name = "Narx ogohlantirishi"
        verbose_name_plural = "Narx ogohlantirishlari"
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="uniq_alert_per_user_product")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id}: {self.product_id} <= {self.target_price}"
