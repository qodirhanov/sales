from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_http_url(value):
    """Only http/https links may be stored (blocks javascript:, data:, ftp: ...)."""
    if value and urlparse(value).scheme.lower() not in ("http", "https"):
        raise ValidationError(_("Faqat http:// yoki https:// havola ruxsat etiladi."))
