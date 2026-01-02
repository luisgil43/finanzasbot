# accounts/signals.py
from __future__ import annotations

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    """
    Asegura que todo User tenga UserProfile.
    - En create: lo crea
    - En update: no hace nada si ya existe
    """
    if not instance.pk:
        return

    # get_or_create evita race conditions / señales duplicadas
    UserProfile.objects.get_or_create(user=instance)