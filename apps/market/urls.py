from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import alerts, views, writes

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="v2-category")
router.register("products", views.ProductViewSet, basename="v2-product")
router.register("districts", views.DistrictViewSet, basename="v2-district")
router.register("locations", views.LocationViewSet, basename="v2-location")
router.register("alerts", alerts.PriceAlertViewSet, basename="v2-alert")

urlpatterns = [
    path("prices/", writes.ReportCreateView.as_view(), name="v2-price-create"),
    path("prices/<int:pk>/confirm/", writes.ReportConfirmView.as_view(), name="v2-price-confirm"),
    path("basket/compare/", views.BasketCompareView.as_view(), name="v2-basket-compare"),
    path("deals/", views.DealsView.as_view(), name="v2-deals"),
    path("product-id-map/", views.ProductIdMapView.as_view(), name="v2-product-id-map"),
    path("", include(router.urls)),
]
