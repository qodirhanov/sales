from django.db.models import Q
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (Category, District, Location, PriceAlert, PriceEntry, Product, Region,
                     compute_normalized_price)
from .services import best_current_price, is_http_url


def absolute_image_url(request, image):
    if not image:
        return None
    return request.build_absolute_uri(image.url) if request else image.url


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    parent = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "emoji", "image", "parent", "product_count")

    def get_image(self, obj):
        return absolute_image_url(self.context.get("request"), obj.image)

    def get_product_count(self, obj):
        annotated = getattr(obj, "product_count", None)  # set by annotate() in the viewset
        if annotated is not None:
            return annotated
        return Product.objects.filter(is_active=True).filter(
            Q(category=obj) | Q(category__parent=obj)).count()


class ProductSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Product
        fields = ("id", "name", "category", "category_name", "base_unit", "is_active",
                  "image", "description", "usage")

    def get_image(self, obj):
        return absolute_image_url(self.context.get("request"), obj.image)


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ("id", "name")


class DistrictSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = ("id", "name", "region")


class LocationSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source="district.name", read_only=True)

    class Meta:
        model = Location
        fields = ("id", "name", "type", "district", "district_name", "address", "website", "lat", "lng", "is_active")


class PriceEntrySerializer(serializers.ModelSerializer):
    confirmations = serializers.SerializerMethodField()

    class Meta:
        model = PriceEntry
        fields = ("id", "product", "location", "price", "quantity", "unit",
                  "normalized_price", "old_price", "is_promo", "source_url", "photo", "created_at",
                  "confirmations")
        read_only_fields = ("id", "normalized_price", "created_at", "confirmations")

    def get_confirmations(self, obj):
        annotated = getattr(obj, "confirmation_count", None)  # annotated in the viewset (no N+1)
        return annotated if annotated is not None else obj.confirmations.count()

    def validate_product(self, product):
        if not product.is_active:
            raise serializers.ValidationError("Product is not active.")
        return product

    def validate_location(self, location):
        if not location.is_active:
            raise serializers.ValidationError("Location is not active.")
        return location

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be positive.")
        return value

    def validate_source_url(self, value):
        if value and not is_http_url(value):
            raise serializers.ValidationError("Faqat http:// yoki https:// havola ruxsat etiladi.")
        return value

    def validate(self, attrs):
        old_price = attrs.get("old_price")
        if attrs.get("is_promo") and old_price is None:
            raise serializers.ValidationError({"old_price": "Aksiya uchun eski narx kerak."})
        if old_price is not None and old_price <= attrs["price"]:
            raise serializers.ValidationError({"old_price": "Eski narx joriy narxdan katta bo'lishi kerak."})
        try:
            compute_normalized_price(attrs["product"], attrs["price"], attrs["quantity"], attrs["unit"])
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class PriceAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    base_unit = serializers.CharField(source="product.base_unit", read_only=True)
    current_best = serializers.SerializerMethodField()
    is_reached = serializers.SerializerMethodField()

    class Meta:
        model = PriceAlert
        fields = ("id", "product", "product_name", "base_unit", "target_price", "is_active",
                  "current_best", "is_reached", "triggered_at", "created_at")
        read_only_fields = ("id", "triggered_at", "created_at")

    def validate_product(self, product):
        if not product.is_active:
            raise serializers.ValidationError("Product is not active.")
        return product

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

    def _best(self, obj):
        cache = self.context.setdefault("_best_cache", {})
        if obj.product_id not in cache:
            cache[obj.product_id] = best_current_price(obj.product)
        return cache[obj.product_id]

    def get_current_best(self, obj):
        return self._best(obj)

    def get_is_reached(self, obj):
        best = self._best(obj)
        return best is not None and best <= obj.target_price
