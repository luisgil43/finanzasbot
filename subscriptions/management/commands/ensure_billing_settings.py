from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from subscriptions.models import BillingSettings


class Command(BaseCommand):
    help = "Asegura BillingSettings para usuarios (owner). Idempotente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-users",
            action="store_true",
            help="Crea BillingSettings para TODOS los usuarios que no tengan (por defecto solo staff/superuser).",
        )
        parser.add_argument(
            "--owners-only",
            action="store_true",
            help="Alias de comportamiento por defecto: solo staff/superuser.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No escribe en BD, solo muestra conteos.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        U = get_user_model()
        dry_run = bool(options["dry_run"])

        all_users = bool(options["all_users"])
        owners_only = bool(options["owners_only"])

        # Por defecto: solo staff/superuser (owner panel)
        if not all_users:
            qs = U.objects.filter(is_active=True).filter(is_staff=True) | U.objects.filter(is_active=True, is_superuser=True)
            qs = qs.distinct()
        else:
            qs = U.objects.filter(is_active=True)

        missing = qs.filter(billing_settings__isnull=True).distinct()
        missing_count = missing.count()

        if dry_run:
            self.stdout.write(
                f"DRY RUN → users_scope={'ALL' if all_users else 'OWNERS'} missing_billing_settings={missing_count}"
            )
            return

        created = 0
        for u in missing.iterator():
            BillingSettings.objects.create(owner=u)
            created += 1

        still_missing = qs.filter(billing_settings__isnull=True).distinct().count()

        self.stdout.write(self.style.SUCCESS(
            f"OK ensure_billing_settings: created={created} missing_before={missing_count} missing_after={still_missing} scope={'ALL' if all_users else 'OWNERS'}"
        ))