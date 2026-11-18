from django.core.management.base import BaseCommand

from prices.models import Category, District, Location, Product, Region

CATEGORIES = [("Go'sht", "gosht"), ("Un va non", "un"), ("Yog'lar", "yoglar"), ("Shirinliklar", "shirinlik")]
PRODUCTS = [
    ("Mol go'shti lahm", "gosht", "kg"),
    ("Qo'y go'shti", "gosht", "kg"),
    ("Un 1-nav", "un", "kg"),
    ("Paxta yog'i", "yoglar", "l"),
    ("Kungaboqar yog'i", "yoglar", "l"),
    ("Shakar", "shirinlik", "kg"),
]
DISTRICTS = ["Chilonzor tumani", "Yunusobod tumani"]
LOCATIONS = [
    ("Chorsu bozori", "bazaar", "Chilonzor tumani", "Eski shahar"),
    ("Oloy bozori", "bazaar", "Yunusobod tumani", ""),
    ("Supermarket", "shop", "Yunusobod tumani", ""),
]


class Command(BaseCommand):
    help = "Seed catalog data (idempotent)."

    def handle(self, *args, **opts):
        cats = {slug: Category.objects.get_or_create(slug=slug, defaults={"name": name})[0]
                for name, slug in CATEGORIES}
        for name, slug, unit in PRODUCTS:
            Product.objects.get_or_create(name=name, defaults={"category": cats[slug], "base_unit": unit})
        region, _ = Region.objects.get_or_create(name="Toshkent")
        dist = {n: District.objects.get_or_create(region=region, name=n)[0] for n in DISTRICTS}
        for name, typ, d, addr in LOCATIONS:
            Location.objects.get_or_create(name=name, district=dist[d], defaults={"type": typ, "address": addr})
        self.stdout.write(self.style.SUCCESS("Seed data ready."))
