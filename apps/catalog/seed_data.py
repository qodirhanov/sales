"""Starter data for Namangan.

PLACES ARE PLACEHOLDERS: the names are deliberately generic ("Namuna ...") and the coordinates are
scattered around the city centre. Replace them with real markets/shops in the admin before launch.
Products and aliases are common Uzbek market staples; review the pack sizes (qop) with real sellers.
"""

CITY = {"name": "Namangan", "slug": "namangan"}

# (name, slug, sort_order)
CATEGORIES = [
    ("Go'sht", "gosht", 10),
    ("Un va non", "un-va-non", 20),
    ("Don va makaron", "don-va-makaron", 30),
    ("Yog'", "yog", 40),
    ("Sabzavot", "sabzavot", 50),
    ("Meva", "meva", 60),
    ("Sut va tuxum", "sut-va-tuxum", 70),
]

# (name, category slug, default_unit, pack_size or None, [aliases])
PRODUCTS = [
    ("Mol go'shti", "gosht", "kg", None, ["govyadina", "mol go'shti suyaksiz", "mol"]),
    ("Qo'y go'shti", "gosht", "kg", None, ["baranina", "qo'zi go'shti"]),
    ("Tovuq go'shti", "gosht", "kg", None, ["kuritsa", "broyler", "tovuq"]),
    ("Mol qiymasi", "gosht", "kg", None, ["farsh", "qiyma"]),
    ("Un (oliy nav)", "un-va-non", "kg", 50, ["muka", "bug'doy uni", "un"]),
    ("Tandir non", "un-va-non", "dona", None, ["non", "lepyoshka", "patir"]),
    ("Guruch", "don-va-makaron", "kg", 25, ["ris", "devzira"]),
    ("Makaron", "don-va-makaron", "kg", None, ["spagetti", "vermishel"]),
    ("Grechka", "don-va-makaron", "kg", None, ["grechka yormasi", "marjumak"]),
    ("Kungaboqar yog'i", "yog", "litr", None, ["podsolnechnoe maslo", "o'simlik yog'i"]),
    ("Paxta yog'i", "yog", "litr", None, ["xlopkovoe maslo", "chigit yog'i"]),
    ("Sariyog'", "yog", "kg", None, ["slivochnoe maslo", "saryog'"]),
    ("Kartoshka", "sabzavot", "kg", None, ["kartofel", "kartoshka sariq"]),
    ("Piyoz", "sabzavot", "kg", None, ["luk", "sariq piyoz"]),
    ("Sabzi", "sabzavot", "kg", None, ["morkov", "sabzi sariq"]),
    ("Pomidor", "sabzavot", "kg", None, ["tomat", "pamidor"]),
    ("Bodring", "sabzavot", "kg", None, ["ogurets", "bodring issiqxona"]),
    ("Karam", "sabzavot", "kg", None, ["kapusta", "oq karam"]),
    ("Olma", "meva", "kg", None, ["yabloko", "olma qizil"]),
    ("Banan", "meva", "kg", None, ["banan import"]),
    ("Uzum", "meva", "kg", None, ["vinograd", "uzum oq"]),
    ("Sut", "sut-va-tuxum", "litr", None, ["moloko", "sigir suti"]),
    ("Qatiq", "sut-va-tuxum", "kg", None, ["qatiq suti"]),
    ("Tuxum", "sut-va-tuxum", "dona", 30, ["yaytso", "tovuq tuxumi"]),
    ("Pishloq", "sut-va-tuxum", "kg", None, ["sir", "suzma pishloq"]),
]

# (name, type, address, lat, lng, opens, closes)
PLACES = [
    ("Namuna bozor 1", "bazaar", "Namangan, markaz (namuna)", "40.998300", "71.672600", "06:00", "18:00"),
    ("Namuna bozor 2", "bazaar", "Namangan, shimol (namuna)", "41.012000", "71.668000", "06:00", "18:00"),
    ("Namuna bozor 3", "bazaar", "Namangan, janub (namuna)", "40.985000", "71.680000", "06:00", "17:00"),
    ("Namuna do'kon 1", "shop", "Namangan, markaz (namuna)", "40.999500", "71.675000", "08:00", "21:00"),
    ("Namuna do'kon 2", "shop", "Namangan, sharq (namuna)", "40.994000", "71.690000", "08:00", "21:00"),
    ("Namuna do'kon 3", "shop", "Namangan, g'arb (namuna)", "41.003000", "71.655000", "08:00", "20:00"),
    ("Namuna supermarket 1", "supermarket", "Namangan, markaz (namuna)", "40.996000", "71.670000", "09:00", "22:00"),
    ("Namuna supermarket 2", "supermarket", "Namangan, shimol (namuna)", "41.008000", "71.676000", "09:00", "22:00"),
]
