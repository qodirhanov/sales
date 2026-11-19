"""Domain errors. The API layer maps them to HTTP codes; `code` is stable for clients."""
from django.utils.translation import gettext as _


class VerificationError(Exception):
    code = "verification_error"

    def __init__(self, message=None):
        super().__init__(message or self.default_message())

    def default_message(self):
        return _("Amalni bajarib bo'lmadi.")


class RateLimited(VerificationError):
    code = "rate_limited"

    def __init__(self, retry_after):
        self.retry_after = retry_after  # timedelta until the user may report again
        super().__init__()

    def default_message(self):
        return _("Bu mahsulot narxini shu joy uchun yaqinda kiritgansiz. Keyinroq urinib ko'ring.")


class SelfConfirmation(VerificationError):
    code = "self_confirmation"

    def default_message(self):
        return _("O'z narxingizni tasdiqlay olmaysiz.")


class AlreadyConfirmed(VerificationError):
    code = "already_confirmed"

    def default_message(self):
        return _("Siz bu narxni allaqachon tasdiqlagansiz.")


class ReportClosed(VerificationError):
    code = "report_closed"

    def default_message(self):
        return _("Bu narx rad etilgan, tasdiqlab bo'lmaydi.")
