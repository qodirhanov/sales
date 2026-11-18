"""Uzbek phone number handling. Canonical form: +998XXXXXXXXX (13 chars)."""
import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

_NON_DIGITS = re.compile(r"\D+")


def normalize_phone(raw):
    """'+998 90 123-45-67', '998901234567' and '90 123 45 67' all become '+998901234567'.
    Raises ValueError for anything that is not a plausible Uzbek number."""
    digits = _NON_DIGITS.sub("", str(raw or ""))
    if len(digits) == 9:                       # local form without the country code
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        raise ValueError("Not an Uzbek phone number")
    return "+" + digits


def validate_phone(value):
    try:
        normalize_phone(value)
    except ValueError:
        raise ValidationError(_("Telefon raqam noto'g'ri. Masalan: +998 90 123 45 67"))
