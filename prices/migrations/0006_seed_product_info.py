from django.db import migrations

# Only fills EMPTY fields, so it never overwrites edits made in the admin.
CATEGORY_EMOJI = {
    "gosht": "🥩",
    "un": "🌾",
    "yoglar": "🫒",
    "shirinlik": "🍬",
}

PRODUCT_INFO = {
    "Mol go'shti lahm": (
        "Mol go'shtining suyaksiz, yog'siz qismi (lahm). Yangi, sovutilgan holda kilogrammlab sotiladi.",
        "Sho'rva, qovurma, manti, kabob va palov kabi taomlar tayyorlashda ishlatiladi. Oqsil va temirga boy.",
    ),
    "Qo'y go'shti": (
        "Qo'zi yoki qo'yning yangi go'shti, odatda suyagi bilan kilogrammlab sotiladi.",
        "Palov, shurpa, qovurdoq, kabob va dimlama tayyorlashda, shuningdek bayram dasturxonlarida ishlatiladi.",
    ),
    "Un 1-nav": (
        "Bug'doydan tortilgan 1-nav un. Non va xamir mahsulotlari uchun mos, kilogrammlab sotiladi.",
        "Non, patir, lag'mon, somsa, chuchvara va pishiriqlar uchun xamir qorishda ishlatiladi.",
    ),
    "Paxta yog'i": (
        "Chigitdan olinadigan o'simlik yog'i. Litrlab idishda sotiladi.",
        "Palov, qovurma, somsa va boshqa milliy taomlarni qovurish va pishirishda keng ishlatiladi.",
    ),
    "Kungaboqar yog'i": (
        "Kungaboqar urug'idan olinadigan o'simlik yog'i. Litrlab idishda sotiladi.",
        "Qovurish, salat to'qash va pishiriqlar tayyorlashda ishlatiladi. Hidi yengil, kundalik oshxona uchun qulay.",
    ),
    "Shakar": (
        "Oq kristall shakar (qand). Kilogrammlab qadoqlangan holda sotiladi.",
        "Choy va kofeni shirinlash, murabbo, kompot, shirinlik va pishiriq tayyorlashda ishlatiladi.",
    ),
}


def forwards(apps, schema_editor):
    Category = apps.get_model("prices", "Category")
    Product = apps.get_model("prices", "Product")
    for slug, emoji in CATEGORY_EMOJI.items():
        Category.objects.filter(slug=slug, emoji="").update(emoji=emoji)
    for name, (description, usage) in PRODUCT_INFO.items():
        Product.objects.filter(name=name, description="").update(description=description)
        Product.objects.filter(name=name, usage="").update(usage=usage)


class Migration(migrations.Migration):
    dependencies = [("prices", "0005_marketplace_fields")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
