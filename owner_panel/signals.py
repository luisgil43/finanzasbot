# owner_panel/signals.py
from __future__ import annotations

from django.apps import apps
from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver

STAFF_GROUPS = ["admin_general", "finance", "support"]


@receiver(post_migrate)
def ensure_staff_groups(sender, **kwargs):
    """
    Crea los groups staff automáticamente después de migrar.
    (Se ejecuta cada migrate; get_or_create es idempotente)
    """
    # Solo cuando migra owner_panel (para no correr en todas las apps)
    if sender.name != "owner_panel":
        return

    for name in STAFF_GROUPS:
        Group.objects.get_or_create(name=name)

    # Si quieres asegurar BillingSettings singleton también (si existe el modelo):
    try:
        BillingSettings = apps.get_model("subscriptions", "BillingSettings")
        BillingSettings.get_solo()
    except Exception:
        pass