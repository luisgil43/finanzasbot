from __future__ import annotations

from django.core.management.base import BaseCommand

from subscriptions.models import Plan


class Command(BaseCommand):
    help = "Crea/actualiza planes base (free/plus/pro). Idempotente."

    def handle(self, *args, **options):
        data = [
            dict(code=Plan.CODE_FREE, name="Free", price_monthly_clp=0, is_active=True, features={}),
            dict(code=Plan.CODE_PLUS, name="Plus", price_monthly_clp=3990, is_active=True, features={}),
            dict(code=Plan.CODE_PRO,  name="Pro",  price_monthly_clp=7990, is_active=True, features={}),
        ]

        created = 0
        updated = 0

        for row in data:
            code = row.pop("code")
            obj, was_created = Plan.objects.update_or_create(code=code, defaults=row)
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        total = Plan.objects.count()
        self.stdout.write(self.style.SUCCESS(f"OK seed_plans: created={created} updated={updated} total={total}"))