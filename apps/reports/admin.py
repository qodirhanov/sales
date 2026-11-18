from django.contrib import admin
from django.utils import timezone

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

    def _set_status(self, request, queryset, status):
        updated = queryset.update(status=status, status_changed_at=timezone.now())
        self.message_user(request, f"{updated} ta xabar holati o'zgardi.")

    @admin.action(description="Tanlanganlarni tasdiqlangan qilish")
    def mark_confirmed(self, request, queryset):
        self._set_status(request, queryset, PriceReport.Status.CONFIRMED)

    @admin.action(description="Tanlanganlarni rad etish")
    def mark_rejected(self, request, queryset):
        self._set_status(request, queryset, PriceReport.Status.REJECTED)

    @admin.action(description="Tanlanganlarni shubhali deb belgilash")
    def mark_flagged(self, request, queryset):
        self._set_status(request, queryset, PriceReport.Status.FLAGGED)


@admin.register(Confirmation)
class ConfirmationAdmin(admin.ModelAdmin):
    list_display = ("report", "user", "weight", "created_at")
    list_select_related = ("report", "user")
    autocomplete_fields = ("report", "user")
