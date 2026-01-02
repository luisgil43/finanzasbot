from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from subscriptions.models import Plan, UserSubscription


class Command(BaseCommand):
    help = "Asegura que cada usuario tenga una suscripción (default: FREE activa). Idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--plan", default="free", help="Plan code a asignar (default: free)")
        parser.add_argument("--dry-run", action="store_true", help="No escribe en BD, solo muestra conteos")

    @transaction.atomic
    def handle(self, *args, **options):
        plan_code = (options["plan"] or "free").strip().lower()
        dry_run = bool(options["dry_run"])

        plan = Plan.objects.filter(code__iexact=plan_code).first()
        if not plan:
            raise SystemExit(f"No existe Plan(code='{plan_code}'). Ejecuta: python manage.py seed_plans")

        U = get_user_model()

        # usuarios sin ninguna suscripción
        missing_qs = U.objects.filter(subscriptions__isnull=True).distinct()
        missing_count = missing_qs.count()

        if dry_run:
            self.stdout.write(f"DRY RUN → missing={missing_count} using_plan={plan.code}")
            return

        created = 0
        now = timezone.now()

        for u in missing_qs.iterator():
            UserSubscription.objects.create(
                user=u,
                plan=plan,
                status=UserSubscription.STATUS_ACTIVE,
                started_at=now,
            )
            created += 1

        still_missing = U.objects.filter(subscriptions__isnull=True).distinct().count()
        self.stdout.write(self.style.SUCCESS(
            f"OK ensure_subscriptions: created={created} missing_before={missing_count} missing_after={still_missing} plan={plan.code}"
        ))