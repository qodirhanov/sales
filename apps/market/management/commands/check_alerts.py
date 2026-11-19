"""Fire price alerts on the new models. Run periodically (cron / Task Scheduler), e.g. every 15 minutes:
    python manage.py check_alerts
E-mail goes to users with an address (console backend in dev, see EMAIL_BACKEND); triggered_at and
last_notified_price are always updated so the API can show it."""
from django.core.management.base import BaseCommand

from apps.market.alerts import fire_due_alerts


class Command(BaseCommand):
    help = "Check active price alerts and notify users whose target price was reached."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f"{fire_due_alerts()} ta ogohlantirish yuborildi."))
