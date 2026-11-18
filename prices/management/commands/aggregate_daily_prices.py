from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from prices.models import DailyPriceStat, PriceEntry
from prices.services import quantize_money

TZ = ZoneInfo("Asia/Tashkent")


class Command(BaseCommand):
    help = "Aggregate non-flagged PriceEntry rows into DailyPriceStat for one day (default: yesterday, Asia/Tashkent)."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD (Asia/Tashkent local date)")

    def handle(self, *args, **opts):
        if opts["date"]:
            try:
                day = date.fromisoformat(opts["date"])
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD")
        else:
            day = timezone.now().astimezone(TZ).date() - timedelta(days=1)

        start = datetime.combine(day, time.min, tzinfo=TZ)
        end = start + timedelta(days=1)
        rows = PriceEntry.objects.filter(
            is_flagged=False, created_at__gte=start, created_at__lt=end
        ).values_list("product_id", "location_id", "normalized_price")

        groups = defaultdict(list)
        for product_id, location_id, value in rows:
            groups[(product_id, location_id)].append(value)

        with transaction.atomic():
            for (product_id, location_id), values in groups.items():
                DailyPriceStat.objects.update_or_create(
                    product_id=product_id,
                    location_id=location_id,
                    date=day,
                    defaults={
                        "min_price": min(values),
                        "max_price": max(values),
                        "median_price": quantize_money(median(values)),
                        "count": len(values),
                    },
                )
        self.stdout.write(self.style.SUCCESS(f"{day}: {len(groups)} stat rows written."))
