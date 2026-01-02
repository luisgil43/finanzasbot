# accounts/management/commands/backfill_profiles.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import UserProfile


class Command(BaseCommand):
    help = "Crea UserProfile para usuarios que no lo tengan."

    def handle(self, *args, **options):
        User = get_user_model()
        created = 0

        for u in User.objects.all().iterator():
            _, was_created = UserProfile.objects.get_or_create(user=u)
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f"OK: profiles creados={created}"))