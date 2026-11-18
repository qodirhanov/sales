"""Unit conversion: every report is normalised to a price per ONE product.default_unit.

Example: 400 000 so'm for 50 kg of flour -> 8 000 so'm / kg. A "qop" (sack) is converted with the
product's pack_size, so "1 qop = 50 kg" lives on the product and not in every report.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

QOP = "qop"

# unit typed in a report -> multiplier into the product's default unit
_FACTORS = {
    "kg": {"kg": Decimal("1"), "g": Decimal("0.001")},
    "litr": {"litr": Decimal("1"), "ml": Decimal("0.001")},
    "dona": {"dona": Decimal("1")},
}


def unit_factor(product, unit):
    if unit == QOP:
        if not product.pack_size:
            raise ValidationError({"unit": _("Bu mahsulot qopda sotilmaydi.")})
        return Decimal(product.pack_size)
    try:
        return _FACTORS[product.default_unit][unit]
    except KeyError:
        raise ValidationError({"unit": _("Bu birlik shu mahsulotga mos kelmaydi.")})


def compute_normalized_price(product, price, quantity, unit):
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError({"quantity": _("Miqdor noldan katta bo'lishi kerak.")})
    base_qty = quantity * unit_factor(product, unit)
    return (Decimal(price) / base_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
