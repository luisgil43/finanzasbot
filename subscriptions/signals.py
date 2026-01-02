from __future__ import annotations

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from subscriptions.models import Plan, UserSubscription


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_subscription_on_user_create(sender, instance, created, **kwargs):
    if not created:
        return

    if UserSubscription.objects.filter(user=instance).exists():
        return

    free = Plan.objects.filter(code=Plan.CODE_FREE).first()
    if not free:
        # Si aún no existen planes, no rompemos el signup
        # (pero conviene correr seed_plans en deploy)
        return

    UserSubscription.objects.create(
        user=instance,
        plan=free,
        status=UserSubscription.STATUS_ACTIVE,
    )