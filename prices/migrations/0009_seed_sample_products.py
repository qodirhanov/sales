from django.db import migrations

# slug -> [(name, base_unit, description, usage)]. Created attached directly to that category.
SAMPLES = {
    "kiyimlar": [
        ("Erkaklar ko'ylagi", "piece", "Erkaklar uchun paxtali, uzun yengli klassik ko'ylak. Turli o'lcham va ranglarda sotiladi.", "Ish, o'qish va bayramlarda kundalik kiyim sifatida kiyiladi."),
        ("Ayollar ko'ylagi", "piece", "Ayollar uchun yengil matodan tikilgan ko'ylak yoki libos. Milliy va zamonaviy uslublarda mavjud.", "Kundalik va tantanali tadbirlarda kiyiladi."),
        ("Bolalar kurtkasi", "piece", "Bolalar uchun issiq, shamol o'tkazmaydigan kurtka.", "Kuz va qish mavsumida bolalarni sovuqdan asrash uchun kiyiladi."),
        ("Sport krossovkasi", "piece", "Yengil va qulay tagli sport poyabzali.", "Yugurish, mashg'ulot va kundalik yurish uchun ishlatiladi."),
    ],
    "mebel": [
        ("Divan", "piece", "Mehmonxona uchun yumshoq, ochiladigan divan.", "Mehmonlarni kutish va dam olish, ba'zan yotish uchun ishlatiladi."),
        ("Ish stoli", "piece", "Kompyuter va hujjatlar uchun mo'ljallangan yozuv stoli.", "Uyda yoki ofisda ishlash va dars tayyorlash uchun ishlatiladi."),
        ("Garderob", "piece", "Kiyim-kechak saqlash uchun sig'imli shkaf.", "Kiyim, ko'rpa-to'shak va shaxsiy buyumlarni tartibli saqlash uchun ishlatiladi."),
        ("Stul", "piece", "Yog'och yoki metall karkasli oshxona va yemakxona stuli.", "Dasturxon va ish stoli yonida o'tirish uchun ishlatiladi."),
    ],
    "ichimliklar": [
        ("Qora choy", "kg", "Barg qora choy, kilogrammlab yoki qadoqlab sotiladi.", "Kundalik choyxo'rlik va mehmon kutishda damlab ichiladi."),
        ("Ko'k choy", "kg", "O'zbekistonda keng iste'mol qilinadigan barg ko'k choy.", "Palov va ovqatdan keyin, dasturxonda damlab ichiladi."),
        ("Mineral suv", "l", "Gazli yoki gazsiz ichimlik mineral suvi, butilkada sotiladi.", "Chanqoqni qondirish va kundalik ichish uchun ishlatiladi."),
        ("Sharbat", "l", "Meva sharbati, karton yoki shisha qadoqda litrlab sotiladi.", "Nonushta va tushlikda sovuq ichimlik sifatida, bolalar uchun ham ichiladi."),
    ],
    "gullar": [
        ("Atirgul guldastasi", "piece", "Yangi uzilgan atirgullardan tuzilgan guldasta.", "Tug'ilgan kun, to'y va boshqa bayramlarda sovg'a qilinadi."),
        ("Lola", "piece", "Bahor faslida sotiladigan yangi lola guldastasi.", "8-mart va bahor bayramlarida sovg'a yoki uy bezagi sifatida ishlatiladi."),
        ("Xonaki gullar (kaktus)", "piece", "Tuvakda o'sadigan, parvarishi oson kaktus.", "Xona va ish stolini bezash uchun ishlatiladi."),
        ("Orkideya", "piece", "Tuvakdagi gullaydigan xonaki orkideya.", "Uy va ofis bezagi, shuningdek sovg'a sifatida ishlatiladi."),
    ],
    "qurilmalar": [
        ("Smartfon", "piece", "Sensorli ekranli, kamerali va internetga ulanadigan mobil telefon.", "Qo'ng'iroq, aloqa, internet va suratga olish uchun ishlatiladi."),
        ("Noutbuk", "piece", "Ko'chma shaxsiy kompyuter.", "O'qish, ish, dasturlash va ko'ngilochar maqsadlarda ishlatiladi."),
        ("Quloqchin", "piece", "Simli yoki simsiz (bluetooth) quloqchin.", "Musiqa tinglash va telefon orqali gaplashish uchun ishlatiladi."),
        ("Planshet", "piece", "Sensorli ekranli yengil planshet kompyuter.", "Kitob o'qish, video ko'rish va o'qishda yordamchi qurilma sifatida ishlatiladi."),
    ],
    "sovgalar": [
        ("Sovg'a to'plami", "piece", "Bayram uchun tayyor qadoqlangan sovg'a to'plami.", "Tug'ilgan kun va bayramlarda yaqinlarga sovg'a qilinadi."),
        ("Shokolad to'plami", "piece", "Qutida qadoqlangan turli xil shokoladlar to'plami.", "Shirinlik sifatida sovg'a qilinadi yoki choy bilan beriladi."),
        ("Soat", "piece", "Qo'l soati, erkak va ayollar uchun turli modellarda.", "Vaqtni bilish va chiroyli sovg'a sifatida ishlatiladi."),
        ("Sumka", "piece", "Teri yoki gazlamadan tikilgan sumka.", "Kundalik buyumlarni olib yurish va sovg'a sifatida ishlatiladi."),
    ],
    "bolalar-uchun": [
        ("Bolalar o'yinchog'i", "piece", "Yumshoq yoki plastik, xavfsiz materialdan yasalgan o'yinchoq.", "Bolalarning o'yin va rivojlanishi uchun ishlatiladi."),
        ("Bolalar aravachasi", "piece", "Chaqaloqlar uchun yengil, yig'iladigan aravacha.", "Chaqaloqni ko'chada sayr qildirish uchun ishlatiladi."),
        ("Maktab ryukzagi", "piece", "O'quvchilar uchun yengil va mustahkam ryukzak.", "Kitob va daftarlarni maktabga olib borish uchun ishlatiladi."),
        ("Bolalar yotoqchasi", "piece", "Chaqaloqlar uchun xavfsiz to'rli yotoqcha.", "Chaqaloqning uxlashi uchun ishlatiladi."),
    ],
    "maishiy-texnika": [
        ("Muzlatgich", "piece", "Oziq-ovqatni sovuq saqlaydigan maishiy muzlatgich.", "Go'sht, sut mahsulotlari va sabzavotni buzilmasdan saqlash uchun ishlatiladi."),
        ("Kir yuvish mashinasi", "piece", "Avtomatik kir yuvish mashinasi.", "Kiyim va ko'rpa-to'shakni yuvish uchun ishlatiladi."),
        ("Changyutgich", "piece", "Uy va gilam tozalash uchun elektr changyutgich.", "Xonalarni chang va axlatdan tozalash uchun ishlatiladi."),
        ("Mikroto'lqinli pech", "piece", "Ovqatni isitish va pishirish uchun mikroto'lqinli pech.", "Tayyor ovqatni tez isitish va oddiy taomlarni pishirish uchun ishlatiladi."),
    ],
    "gozallik-salomatlik": [
        ("Shampun", "piece", "Soch yuvish uchun shampun, flakonda sotiladi.", "Sochni yuvish va parvarish qilish uchun ishlatiladi."),
        ("Yuz kremi", "piece", "Teri uchun namlovchi yuz kremi.", "Yuz terisini namlash va himoya qilish uchun har kuni ishlatiladi."),
        ("Tish pastasi", "piece", "Tish va milklarni parvarish qiluvchi pasta.", "Tishni kuniga ikki marta tozalash uchun ishlatiladi."),
        ("Vitaminlar", "piece", "Qadoqlangan vitaminlar majmuasi.", "Immunitetni mustahkamlash va vitamin yetishmovchiligini to'ldirish uchun ishlatiladi."),
    ],
    "qurilish-tamirlash": [
        ("Sement", "kg", "Qurilish uchun portlandsement, qoplarda sotiladi.", "Beton, qorishma va suvoq tayyorlashda ishlatiladi."),
        ("Bo'yoq", "l", "Devor va shiftlar uchun suv asosidagi bo'yoq.", "Xonalar ichini va tashqarisini ranglash uchun ishlatiladi."),
        ("Parma (drel)", "piece", "Elektr parma, teshik ochish va burama mahkamlash uchun.", "Devor, yog'och va metallda teshik ochish uchun ishlatiladi."),
        ("Kafel", "piece", "Pol va devor uchun keramik plitka.", "Hammom, oshxona va xonalar polini yoki devorini qoplash uchun ishlatiladi."),
    ],
    "avtomobil": [
        ("Dvigatel moyi", "l", "Avtomobil dvigateli uchun motor moyi.", "Dvigatelni moylash va ishqalanishdan asrash uchun almashtirib turiladi."),
        ("Avtomobil akkumulyatori", "piece", "Avtomobilni ishga tushiruvchi qo'rg'oshin-kislotali akkumulyator.", "Dvigatelni yurgizish va elektr jihozlarini quvvatlash uchun ishlatiladi."),
        ("Avtomobil shinasi", "piece", "Yengil avtomobil uchun rezina shina.", "G'ildirakka kiydiriladi; yo'lda ishonchli ushlanish uchun ishlatiladi."),
        ("Avtomobil chiroq lampasi", "piece", "Old chiroq uchun avtomobil lampasi.", "Qorong'ida yo'lni yoritish uchun ishlatiladi."),
    ],
    # Food children that had fewer than 2 products.
    "un": [
        ("Makkajo'xori uni", "kg", "Makkajo'xori donidan maydalangan un.", "Non, bo'tqa va pishiriqlar tayyorlashda ishlatiladi."),
    ],
    "shirinlik": [
        ("Asal", "kg", "Tabiiy asalarilar asali, kilogrammlab sotiladi.", "Choy bilan, nonushtada va shamollashda dori sifatida ishlatiladi."),
    ],
}


def forwards(apps, schema_editor):
    Category = apps.get_model("prices", "Category")
    Product = apps.get_model("prices", "Product")
    for slug, items in SAMPLES.items():
        cat = Category.objects.filter(slug=slug).first()
        if cat is None and slug in ("un", "shirinlik"):  # fresh DB without the food sub-types
            cat = Category.objects.filter(slug="oziq-ovqat").first()
        if cat is None:
            continue
        for name, unit, description, usage in items:
            prod, created = Product.objects.get_or_create(
                name=name,
                defaults={"category": cat, "base_unit": unit, "is_active": True,
                          "description": description, "usage": usage},
            )
            if not created:  # only fill empty text fields, never overwrite admin edits
                changed = []
                if not prod.description:
                    prod.description = description
                    changed.append("description")
                if not prod.usage:
                    prod.usage = usage
                    changed.append("usage")
                if changed:
                    prod.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [("prices", "0008_seed_top_categories")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
