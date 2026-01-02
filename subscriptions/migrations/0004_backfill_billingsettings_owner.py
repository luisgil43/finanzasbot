from django.conf import settings
from django.db import migrations


def backfill_owner(apps, schema_editor):
    BillingSettings = apps.get_model("subscriptions", "BillingSettings")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    # Estrategia segura:
    # - Si hay 1 solo superuser, asignarlo
    # - Si no, no hacemos nada (quedan null y luego tú decides)
    su_qs = User.objects.filter(is_superuser=True).order_by("id")
    superuser = su_qs.first()

    if not superuser:
        return

    # Asigna owner a registros existentes sin owner
    BillingSettings.objects.filter(owner__isnull=True).update(owner=superuser)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0003_plan_remove_billingsettings_billing_enabled_and_more"),  # <-- AJUSTA ESTE NOMBRE
    ]

    operations = [
        migrations.RunPython(backfill_owner, reverse_code=noop),
    ]