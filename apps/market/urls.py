from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="v2-category")
router.register("products", views.ProductViewSet, basename="v2-product")
router.register("districts", views.DistrictViewSet, basename="v2-district")
router.register("locations", views.LocationViewSet, basename="v2-location")

urlpatterns = [
    path("basket/compare/", views.BasketCompareView.as_view(), name="v2-basket-compare"),
    path("deals/", views.DealsView.as_view(), name="v2-deals"),
    path("", include(router.urls)),
]
