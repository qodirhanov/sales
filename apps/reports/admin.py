from django.contrib import admin
from django.utils import timezone

from apps.verification import services as verification

from .models import Confirmation, PriceReport


class ConfirmationInline(admin.TabularInline):
    model = Confirmation
    extra = 0
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)


@admin.register(PriceReport)
class PriceReportAdmin(admin.ModelAdmin):
    list_display = ("product", "place", "price", "quantity", "unit", "normalized_price",
                    "status", "is_far", "user", "created_at")
    list_filter = ("status", "is_far", "place__city", "place", "product__category")
    search_fields = ("product__name", "place__name", "user__username")
    readonly_fields = ("normalized_price", "distance_m", "points_awarded")
    list_select_related = ("product", "place", "user")
    date_hierarchy = "created_at"
    autocomplete_fields = ("product", "place", "user")
    inlines = [ConfirmationInline]
    actions = ["mark_confirmed", "mark_rejected", "mark_flagged"]

    @admin.action(description="Tanlanganlarni tasdiqlangan qilish")
    def mark_confirmed(self, request, queryset):
        for report in queryset.select_related("user"):
            verification.mark_confirmed(report)
        self.message_user(request, f"{queryset.count()} ta xabar tasdiqlandi.")

    @admin.action(description="Tanlanganlarni rad etish (muallif ishonchi kamayadi)")
    def mark_rejected(self, request, queryset):
        for report in queryset.select_related("user"):
            verification.reject_report(report)
        self.message_user(request, f"{queryset.count()} ta xabar rad etildi.")

    @admin.action(description="Tanlanganlarni shubhali deb belgilash")
    def mark_flagged(self, request, queryset):
        updated = queryset.update(status=PriceReport.Status.FLAGGED, status_changed_at=timezone.now())
        self.message_user(request, f"{updated} ta xabar shubhali deb belgilandi.")


@admin.register(Confirmation)
class ConfirmationAdmin(admin.ModelAdmin):
    list_display = ("report", "user", "weight", "created_at")
    list_select_related = ("report", "user")
    autocomplete_fields = ("report", "user")
