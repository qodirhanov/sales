from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("products", views.ProductViewSet, basename="product")
router.register("regions", views.RegionViewSet, basename="region")
router.register("districts", views.DistrictViewSet, basename="district")
router.register("locations", views.LocationViewSet, basename="location")
router.register("prices", views.PriceEntryViewSet, basename="price")
router.register("alerts", views.PriceAlertViewSet, basename="alert")

urlpatterns = [
    # TODO: replace with phone (SMS OTP) / Telegram login later.
    path("auth/token/", obtain_auth_token, name="api-token"),
    path("basket/compare/", views.BasketCompareView.as_view(), name="basket-compare"),
    path("deals/", views.DealsView.as_view(), name="deals"),
    path("", include(router.urls)),
]
