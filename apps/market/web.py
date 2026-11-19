"""Server-rendered pages: catalog, product, category, confirm, settings and the account pages.

The pages are thin shells; prices and lists are filled in by app.js from /api/.
"""
from datetime import timedelta
from math import ceil

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.db.models import Case, Count, IntegerField, Sum, When
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import FormView, TemplateView

from apps.accounts.models import UserProfile
from apps.accounts.phone import normalize_phone
from apps.catalog.models import Category, Product
from apps.reports.models import Confirmation, PriceReport
from apps.verification import constants as C

from . import selectors as sel


@method_decorator(ensure_csrf_cookie, name="dispatch")  # JS reads the csrftoken cookie for POSTs
class IndexView(TemplateView):
    template_name = "site/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.annotate(product_count=sel.category_product_count()) \
            .order_by("sort_order", "name")
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ProductDetailView(TemplateView):
    template_name = "site/product_detail.html"

    def get_context_data(self, pk, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = get_object_or_404(Product.objects.select_related("category"), pk=pk, is_active=True)
        offers = sel.build_offers(sel.recent_reports(product=product))
        ctx.update(product=product, offers=offers, best=offers[0] if offers else None, offer_count=len(offers),
                   unit_label=product.get_default_unit_display())
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CategoryDetailView(TemplateView):
    template_name = "site/category.html"

    def get_context_data(self, slug, **kwargs):
        ctx = super().get_context_data(**kwargs)
        category = get_object_or_404(Category, slug=slug)
        products = list(Product.objects.filter(category=category, is_active=True).select_related("category")
                        .order_by("name"))
        by_product = {p.id: [] for p in products}
        for r in sel.recent_reports().filter(product__category=category):
            by_product[r.product_id].append(r)
        items = []
        for p in products:
            offers = sel.build_offers(by_product[p.id])
            items.append({"product": p, "best_offer": offers[0] if offers else None, "offer_count": len(offers)})
        items.sort(key=lambda i: (i["best_offer"] is None,
                                  i["best_offer"]["entry"].normalized_price if i["best_offer"] else 0,
                                  i["product"].name))
        ctx.update(category=category, parent=None, subcategories=[], items=items)
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")  # JS posts to /api/prices/<id>/confirm/
class ConfirmPricesView(LoginRequiredMixin, TemplateView):
    """Open reports by other people that this user has not confirmed yet; suspicious ones first."""
    template_name = "site/confirm.html"
    login_url = "/login/"
    LIMIT = 30
    DAYS = 7

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        S = PriceReport.Status
        reports = (
            PriceReport.objects
            .filter(created_at__gte=timezone.now() - timedelta(days=self.DAYS), status__in=(S.PENDING, S.FLAGGED),
                    product__is_active=True, place__is_active=True)
            .exclude(user=user).exclude(confirmations__user=user)
            .select_related("product", "place__city")
            .annotate(n_confirmed=Count("confirmations", distinct=True), w_confirmed=Sum("confirmations__weight"),
                      _flag_first=Case(When(status=S.FLAGGED, then=0), default=1, output_field=IntegerField()))
            .order_by("_flag_first", "n_confirmed", "-created_at", "-id")[:self.LIMIT]
        )
        items = []
        for r in reports:
            flagged = r.status == S.FLAGGED
            missing = C.FLAGGED_CONFIRM_THRESHOLD - (r.w_confirmed or 0)
            items.append({
                "entry": r, "product": r.product.name, "place": f"{r.place.name}, {r.place.city.name}",
                "unit": r.get_unit_display(), "created_at": r.created_at, "flagged": flagged,
                "count": r.n_confirmed, "price_text": f"{r.price:,}".replace(",", " "),
                "quantity": f"{r.quantity.normalize():f}",
                "need_more": max(0, ceil(float(missing))) if flagged else 0,
            })
        ctx["items"] = items
        ctx["my_confirmed"] = Confirmation.objects.filter(user=user).count()
        return ctx


# ---------------------------------------------------------------- account pages
class SignupForm(UserCreationForm):
    """Username + password only for now. Phone/Telegram login will replace this later."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Login"
        self.fields["username"].help_text = "Harf, raqam va @ . + - _ belgilari, 150 tagacha."
        self.fields["password1"].label = "Parol"
        self.fields["password1"].help_text = "Kamida 8 ta belgi, faqat raqamdan iborat bo'lmasin."
        self.fields["password2"].label = "Parolni takrorlang"
        self.fields["password2"].help_text = ""


class SignupView(FormView):
    template_name = "site/signup.html"
    form_class = SignupForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)  # straight in, no second login step
        nxt = self.request.POST.get("next") or "/"
        if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={self.request.get_host()}):
            nxt = "/"  # block open redirects
        return redirect(nxt)


class AppPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "site/password_change.html"
    success_url = reverse_lazy("settings")
    login_url = "/login/"

    def form_valid(self, form):
        messages.success(self.request, "Parol muvaffaqiyatli o'zgartirildi.")
        return super().form_valid(form)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SettingsView(LoginRequiredMixin, TemplateView):
    """Own prices and optional shop details (shop name, phone) on the reputation profile."""
    template_name = "site/settings.html"
    login_url = "/login/"
    SHOP_NAME_MAX = UserProfile._meta.get_field("shop_name").max_length

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") != "save_profile":
            messages.error(request, "Noma'lum amal.")
            return redirect("settings")
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        fields = []
        if "shop_name" in request.POST:
            shop = request.POST["shop_name"].strip()
            if len(shop) > self.SHOP_NAME_MAX:
                messages.error(request, f"Do'kon nomi {self.SHOP_NAME_MAX} ta belgidan oshmasligi kerak.")
                return redirect("settings")
            profile.shop_name = shop
            fields.append("shop_name")
        if "phone" in request.POST:
            raw = request.POST["phone"].strip()
            if raw:
                try:
                    phone = normalize_phone(raw)
                except ValueError:
                    messages.error(request, "Telefon raqam noto'g'ri. Masalan: +998 90 123 45 67")
                    return redirect("settings")
                if UserProfile.objects.filter(phone=phone).exclude(pk=profile.pk).exists():
                    messages.error(request, "Bu telefon raqam boshqa hisobda ishlatilgan.")
                    return redirect("settings")
                profile.phone = phone
            else:
                profile.phone = None
            fields.append("phone")
        if fields:
            profile.save(update_fields=fields)
        messages.success(request, "Profil saqlandi.")
        return redirect("settings")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        mine = PriceReport.objects.filter(user=user)
        ctx["profile"] = profile
        ctx["my_entries_count"] = mine.count()
        # Dicts, not models: the template reads e.product / e.location / e.get_unit_display either way.
        ctx["recent_entries"] = [
            {"product": r.product, "location": r.place, "created_at": r.created_at, "price": r.price,
             "quantity": r.quantity, "get_unit_display": r.get_unit_display()}
            for r in mine.select_related("product", "place").order_by("-created_at", "-id")[:10]
        ]
        return ctx
