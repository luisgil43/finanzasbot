from __future__ import annotations

from django.db import migrations, models

CONSTRAINT_NAME = "uniq_transaction_user_telegram_msg"


def drop_constraint_if_exists(apps, schema_editor):
    Transaction = apps.get_model("transactions", "Transaction")
    table = Transaction._meta.db_table
    vendor = schema_editor.connection.vendor

    try:
        if vendor == "sqlite":
            # En sqlite, UniqueConstraint suele ser un INDEX
            schema_editor.execute(f"DROP INDEX IF EXISTS {CONSTRAINT_NAME};")

        elif vendor == "postgresql":
            # En postgres es CONSTRAINT
            schema_editor.execute(
                f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{CONSTRAINT_NAME}";'
            )

        elif vendor == "mysql":
            # En mysql suele ser INDEX
            try:
                schema_editor.execute(f"ALTER TABLE `{table}` DROP INDEX `{CONSTRAINT_NAME}`;")
            except Exception:
                # por si el nombre es constraint y no index
                schema_editor.execute(f"ALTER TABLE `{table}` DROP CONSTRAINT `{CONSTRAINT_NAME}`;")

        else:
            # fallback: intenta DROP INDEX (y si falla, se ignora)
            schema_editor.execute(f"DROP INDEX {CONSTRAINT_NAME};")

    except Exception:
        # Si no existe, o el backend lo maneja distinto, no queremos romper la migración
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0004_fix_drop_uniq_tg"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(drop_constraint_if_exists, reverse_code=migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="transaction",
                    name=CONSTRAINT_NAME,
                ),
            ],
        ),
        migrations.AlterField(
            model_name="transaction",
            name="fx_rate",
            field=models.DecimalField(decimal_places=6, default="1", max_digits=14),
        ),
        migrations.AlterField(
            model_name="transaction",
            name="fx_source",
            field=models.CharField(default="default", max_length=30),
        ),
    ]