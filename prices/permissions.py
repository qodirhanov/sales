from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Profile


class IsSellerOrReadOnly(BasePermission):
    """Anyone may read; only authenticated sellers may write."""
    message = "Narx kiritish uchun sotuvchi bo'lishingiz kerak."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False  # DRF turns this into 401/403 as before
        profile, _ = Profile.objects.get_or_create(user=user)  # never crash on a missing profile
        return profile.is_seller
