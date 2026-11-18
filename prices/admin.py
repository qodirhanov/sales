from django.contrib import admin

from .models import (Category, DailyPriceStat, District, Location, PriceAlert, PriceConfirmation, PriceEntry,
                     Product, Profile, Region)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("emoji", "name", "slug", "parent", "sort_order")
    list_filter = ("parent",)
    list_select_related = ("parent",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "base_unit", "is_active")
    list_filter = ("category", "base_unit", "is_active")
    search_fields = ("name",)


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "region")
    list_filter = ("region",)
    search_fields = ("name",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "district", "address", "website", "is_active")
    list_filter = ("type", "is_active", "district__region", "district")
    search_fields = ("name", "address")


@admin.register(PriceEntry)
class PriceEntryAdmin(admin.ModelAdmin):
    list_display = ("product", "location", "user", "price", "quantity", "unit",
                    "normalized_price", "is_promo", "is_flagged", "created_at")
    list_filter = ("is_promo", "is_flagged", "product", "location", "unit")
    search_fields = ("product__name", "location__name", "user__username")
    readonly_fields = ("normalized_price",)
    date_hierarchy = "created_at"
    list_select_related = ("product", "location", "user")
    actions = ["unflag_entries"]

    @admin.action(description="Tanlangan narxlardan shubhali belgisini olib tashlash")
    def unflag_entries(self, request, queryset):
        updated = queryset.update(is_flagged=False)
        self.message_user(request, f"{updated} ta narxdan shubhali belgisi olib tashlandi.")


@admin.register(DailyPriceStat)
class DailyPriceStatAdmin(admin.ModelAdmin):
    list_display = ("product", "location", "date", "min_price", "median_price", "max_price", "count")
    list_filter = ("product", "location", "date")
    date_hierarchy = "date"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_seller", "shop_name", "phone", "created_at")
    list_filter = ("is_seller",)
    search_fields = ("user__username", "shop_name", "phone")
    list_select_related = ("user",)


@admin.register(PriceConfirmation)
class PriceConfirmationAdmin(admin.ModelAdmin):
    list_display = ("entry", "user", "created_at")
    list_select_related = ("entry", "user")


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "target_price", "is_active", "triggered_at", "last_notified_price")
    list_filter = ("is_active",)
    search_fields = ("user__username", "product__name")
    list_select_related = ("user", "product")
