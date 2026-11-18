from django.apps import AppConfig


class PricesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "prices"
    verbose_name = "Narx kuzatuvchi"

    def ready(self):
        from . import signals  # noqa: F401
