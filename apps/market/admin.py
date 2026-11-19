from django.contrib import admin

from .models import PriceAlert


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "target_price", "is_active", "last_notified_price", "triggered_at")
    list_filter = ("is_active",)
    search_fields = ("user__username", "product__name")
    list_select_related = ("user", "product")
