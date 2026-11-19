"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.templatetags.static import static as static_url
from django.views.generic import RedirectView, TemplateView

from apps.market.web import (AppPasswordChangeView, CategoryDetailView, ConfirmPricesView, IndexView,
                             ProductDetailView, SettingsView, SignupView)

urlpatterns = [
    path('', IndexView.as_view(), name='home'),
    path('product/<int:pk>/', ProductDetailView.as_view(), name='product_detail'),
    path('category/<slug:slug>/', CategoryDetailView.as_view(), name='category_detail'),
    # Saralangan va savat brauzerda (localStorage) saqlanadi; sahifalar API orqali to'ldiriladi.
    path('tasdiqlash/', ConfirmPricesView.as_view(), name='confirm_prices'),
    path('favorites/', TemplateView.as_view(template_name='site/favorites.html'), name='favorites'),
    path('cart/', TemplateView.as_view(template_name='site/cart.html'), name='cart'),
    path('login/', auth_views.LoginView.as_view(
        template_name='site/login.html', redirect_authenticated_user=True), name='login'),
    path('signup/', SignupView.as_view(), name='signup'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    path('settings/', SettingsView.as_view(), name='settings'),
    path('settings/password/', AppPasswordChangeView.as_view(), name='password_change'),
    # Browsers ask for /favicon.ico whatever the <link rel=icon> says; send them to the SVG.
    path('favicon.ico', RedirectView.as_view(url=static_url('img/favicon.svg'), permanent=True)),
    path('admin/', admin.site.urls),
    path('api/', include('apps.market.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
