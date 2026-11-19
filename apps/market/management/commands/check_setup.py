"""Is the database ready? python manage.py check_setup  (read-only, exit code 1 on a failure)."""
from django.core.management.base import BaseCommand

from apps.market.readiness import run_checks

MARK = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}


class Command(BaseCommand):
    help = "Check that cities, products, places (with coordinates) and profiles are in place."

    def handle(self, *args, **options):
        checks = run_checks()
        for level, message in checks:
            self.stdout.write(f"[{MARK[level]}] {message}")
        if any(level == "fail" for level, _ in checks):
            self.stdout.write("Not ready: fix the FAIL lines first.")
            raise SystemExit(1)
        self.stdout.write("Ready." if all(level == "ok" for level, _ in checks) else "Ready, with warnings.")
