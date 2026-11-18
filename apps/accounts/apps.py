from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Foydalanuvchilar"

    def ready(self):
        from . import signals  # noqa: F401  (connects the post_save handler)
