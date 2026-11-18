"""Fire price alerts. Run periodically (cron / Task Scheduler), e.g. every 15 minutes:
    python manage.py check_price_alerts
Delivery: e-mail when the user has an address (console backend in dev, see EMAIL_BACKEND);
the alert's `triggered_at` / `last_notified_price` are always updated so the API/UI can show it."""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from prices.models import PriceAlert
from prices.services import alert_is_due, best_current_price


class Command(BaseCommand):
    help = "Check active price alerts and notify users whose target price was reached."

    def handle(self, *args, **options):
        fired = 0
        alerts = PriceAlert.objects.filter(is_active=True, product__is_active=True).select_related("user", "product")
        best_cache = {}
        for alert in alerts:
            if alert.product_id not in best_cache:
                best_cache[alert.product_id] = best_current_price(alert.product)
            best = best_cache[alert.product_id]
            if best is not None and best > alert.target_price and alert.last_notified_price is not None:
                # Price went back up: re-arm so the next drop notifies again.
                alert.last_notified_price = None
                alert.save(update_fields=["last_notified_price"])
                continue
            if not alert_is_due(alert, best):
                continue
            if alert.user.email:
                send_mail(
                    subject=f"Narx tushdi: {alert.product.name}",
                    message=(f"{alert.product.name} narxi {best} so'm / {alert.product.get_base_unit_display()} "
                             f"ga tushdi (maqsadingiz: {alert.target_price} so'm)."),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[alert.user.email],
                    fail_silently=True,
                )
            alert.triggered_at = timezone.now()
            alert.last_notified_price = best
            alert.save(update_fields=["triggered_at", "last_notified_price"])
            fired += 1
        self.stdout.write(self.style.SUCCESS(f"{fired} ta ogohlantirish yuborildi."))
