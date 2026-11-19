from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from . import alerts, views, writes

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("products", views.ProductViewSet, basename="product")
router.register("districts", views.DistrictViewSet, basename="district")
router.register("locations", views.LocationViewSet, basename="location")
router.register("alerts", alerts.PriceAlertViewSet, basename="alert")

urlpatterns = [
    path("auth/token/", obtain_auth_token, name="api-token"),
    path("prices/", writes.ReportCreateView.as_view(), name="price-create"),
    path("prices/<int:pk>/confirm/", writes.ReportConfirmView.as_view(), name="price-confirm"),
    path("basket/compare/", views.BasketCompareView.as_view(), name="basket-compare"),
    path("deals/", views.DealsView.as_view(), name="deals"),
    path("", include(router.urls)),
]
