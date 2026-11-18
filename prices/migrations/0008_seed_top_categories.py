from django.db import migrations

# (name, slug, emoji) in display order -> sort_order 10, 20, 30 ...
TOP_CATEGORIES = [
    ("Oziq-ovqat", "oziq-ovqat", "🛒"),
    ("Kiyimlar", "kiyimlar", "👕"),
    ("Mebel", "mebel", "🛋️"),
    ("Ichimliklar", "ichimliklar", "🥤"),
    ("Gullar", "gullar", "💐"),
    ("Qurilmalar", "qurilmalar", "📱"),
    ("Sovg'alar", "sovgalar", "🎁"),
    ("Bolalar uchun", "bolalar-uchun", "🧸"),
    ("Maishiy texnika", "maishiy-texnika", "🧺"),
    ("Go'zallik va salomatlik", "gozallik-salomatlik", "💄"),
    ("Qurilish va ta'mirlash", "qurilish-tamirlash", "🧰"),
    ("Avtomobil", "avtomobil", "🚗"),
]

# Existing food sub-types that move under "Oziq-ovqat".
FOOD_SLUGS = ["gosht", "un", "yoglar", "shirinlik"]


def forwards(apps, schema_editor):
    Category = apps.get_model("prices", "Category")
    created = {}
    for i, (name, slug, emoji) in enumerate(TOP_CATEGORIES, start=1):
        cat = Category.objects.filter(slug=slug).first()
        if cat is None and not Category.objects.filter(name=name).exists():  # name is unique too
            cat = Category.objects.create(slug=slug, name=name, emoji=emoji, sort_order=i * 10)
        created[slug] = cat  # existing rows are left exactly as the admin made them
    food = created.get("oziq-ovqat")
    if food is not None:
        # Only attach rows that have no parent yet, so admin choices are never overwritten.
        Category.objects.filter(slug__in=FOOD_SLUGS, parent__isnull=True).exclude(pk=food.pk).update(parent=food)


class Migration(migrations.Migration):
    dependencies = [("prices", "0007_category_parent_sort_order")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
