from django.contrib import admin

from .models import ProductStats, ReferencePrice


@admin.register(ProductStats)
class ProductStatsAdmin(admin.ModelAdmin):
    list_display = ("product", "city", "place", "current_price", "city_avg", "week_change_pct",
                    "sample_count", "computed_at")
    list_filter = ("city",)
    search_fields = ("product__name", "place__name")
    list_select_related = ("product", "city", "place")
    readonly_fields = ("computed_at",)


@admin.register(ReferencePrice)
class ReferencePriceAdmin(admin.ModelAdmin):
    list_display = ("product", "region", "date", "min_price", "max_price", "source")
    list_filter = ("source", "region")
    search_fields = ("product__name",)
    date_hierarchy = "date"
    autocomplete_fields = ("product",)
