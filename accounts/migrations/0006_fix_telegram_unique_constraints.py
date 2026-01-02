# accounts/migrations/000X_fix_telegram_unique_constraints.py
from django.db import migrations, models
from django.db.models import Q


def empty_strings_to_null(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    UserProfile.objects.filter(telegram_link_code="").update(telegram_link_code=None)
    UserProfile.objects.filter(telegram_user_id="").update(telegram_user_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_userprofile_telegram_chat_id"),  # 👈 AJUSTA ESTO
    ]

    operations = [
        # 1) Quitar unique=True a nivel de campo (esto elimina el unique constraint/index viejo)
        migrations.AlterField(
            model_name="userprofile",
            name="telegram_user_id",
            field=models.CharField(max_length=32, blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="telegram_link_code",
            field=models.CharField(max_length=64, blank=True, null=True),
        ),

        # 2) Convertir "" a NULL para evitar choques
        migrations.RunPython(empty_strings_to_null, migrations.RunPython.noop),

        # 3) Crear unique condicional (solo cuando hay valor real)
        migrations.AddConstraint(
            model_name="userprofile",
            constraint=models.UniqueConstraint(
                fields=["telegram_user_id"],
                name="uniq_userprofile_telegram_user_id_when_present",
                condition=Q(telegram_user_id__isnull=False) & ~Q(telegram_user_id=""),
            ),
        ),
        migrations.AddConstraint(
            model_name="userprofile",
            constraint=models.UniqueConstraint(
                fields=["telegram_link_code"],
                name="uniq_userprofile_telegram_link_code_when_present",
                condition=Q(telegram_link_code__isnull=False) & ~Q(telegram_link_code=""),
            ),
        ),
    ]