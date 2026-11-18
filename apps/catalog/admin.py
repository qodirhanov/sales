from django.contrib import admin

from .models import Category, City, Place, Product, ProductAlias


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


class ProductAliasInline(admin.TabularInline):
    model = ProductAlias
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "default_unit", "pack_size", "is_active")
    list_filter = ("category", "default_unit", "is_active")
    search_fields = ("name", "aliases__alias", "search_key")
    inlines = [ProductAliasInline]


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "city", "address", "is_active")
    list_filter = ("type", "city", "is_active")
    search_fields = ("name", "address")
