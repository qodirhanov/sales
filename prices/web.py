"""Server-rendered pages. The page itself is a thin shell; data comes from /api/ via fetch()."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import FormView, TemplateView

from .models import Category, PriceEntry, Product, Profile
from .services import build_offers, category_product_count, recent_entries


@method_decorator(ensure_csrf_cookie, name="dispatch")  # JS reads csrftoken cookie for POST /api/prices/
class IndexView(TemplateView):
    template_name = "prices/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.filter(parent__isnull=True).annotate(
            product_count=category_product_count()
        ).order_by("sort_order", "name")
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ProductDetailView(TemplateView):
    template_name = "prices/product_detail.html"

    def get_context_data(self, pk, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = get_object_or_404(Product.objects.select_related("category__parent"), pk=pk, is_active=True)
        offers = build_offers(recent_entries(product=product))
        ctx.update(product=product, offers=offers, best=offers[0] if offers else None,
                   offer_count=len(offers), unit_label=product.get_base_unit_display())
        return ctx


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CategoryDetailView(TemplateView):
    template_name = "prices/category.html"

    def get_context_data(self, slug, **kwargs):
        ctx = super().get_context_data(**kwargs)
        category = get_object_or_404(Category.objects.select_related("parent"), slug=slug)
        subcategories = list(category.children.annotate(product_count=category_product_count())
                             .order_by("sort_order", "name"))
        # A parent page also lists its children's products (one level only, by design).
        scope = Q(category=category) | Q(category__parent=category)
        products = list(Product.objects.filter(scope, is_active=True).select_related("category")
                        .order_by("name"))
        by_product = {p.id: [] for p in products}
        for e in recent_entries().filter(Q(product__category=category) | Q(product__category__parent=category)):
            by_product[e.product_id].append(e)
        items = []
        for p in products:
            offers = build_offers(by_product[p.id])
            items.append({"product": p, "best_offer": offers[0] if offers else None,
                          "offer_count": len(offers)})
        items.sort(key=lambda i: (i["best_offer"] is None,
                                  i["best_offer"]["entry"].normalized_price if i["best_offer"] else 0,
                                  i["product"].name))
        ctx.update(category=category, parent=category.parent, subcategories=subcategories, items=items)
        return ctx


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
    template_name = "prices/signup.html"
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


SHOP_NAME_MAX = Profile._meta.get_field("shop_name").max_length
PHONE_MAX = Profile._meta.get_field("phone").max_length


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "prices/settings.html"
    login_url = "/login/"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile, _ = Profile.objects.get_or_create(user=user)
        ctx["profile"] = profile
        ctx["my_entries_count"] = PriceEntry.objects.filter(user=user).count()
        ctx["recent_entries"] = list(
            PriceEntry.objects.filter(user=user).select_related("product", "location")
            .order_by("-created_at", "-id")[:10]
        )
        return ctx

    def post(self, request, *args, **kwargs):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        action = request.POST.get("action")
        if action not in ("become_seller", "stop_seller", "save_profile"):
            messages.error(request, "Noma'lum amal.")
            return redirect("settings")

        if action == "stop_seller":
            profile.is_seller = False
            profile.save(update_fields=["is_seller"])
            messages.success(request, "Siz endi xaridorsiz. Narx kiritish o'chirildi.")
            return redirect("settings")

        # become_seller / save_profile may carry shop_name + phone; only fields that were sent are touched.
        fields = []
        for name, limit, label in (("shop_name", SHOP_NAME_MAX, "Do'kon nomi"), ("phone", PHONE_MAX, "Telefon")):
            if name in request.POST:
                value = request.POST[name].strip()
                if len(value) > limit:
                    messages.error(request, f"{label} {limit} ta belgidan oshmasligi kerak.")
                    return redirect("settings")
                setattr(profile, name, value)
                fields.append(name)
        if action == "become_seller":
            profile.is_seller = True
            fields.append("is_seller")
            messages.success(request, "Tabriklaymiz, siz endi sotuvchisiz! Narx kiritishingiz mumkin.")
        else:
            messages.success(request, "Profil saqlandi.")
        if fields:
            profile.save(update_fields=fields)
        return redirect("settings")


class AppPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "prices/password_change.html"
    success_url = reverse_lazy("settings")
    login_url = "/login/"

    def form_valid(self, form):
        messages.success(self.request, "Parol muvaffaqiyatli o'zgartirildi.")
        return super().form_valid(form)
