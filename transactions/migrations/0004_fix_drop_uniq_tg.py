from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("transactions", "0003_remove_transaction_uniq_transaction_user_telegram_msg_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # SQLite: si no existe, IF EXISTS evita el error
                "DROP INDEX IF EXISTS uniq_transaction_user_telegram_msg;",
                # por si se creó como constraint “UNIQUE” en tabla (a veces otro nombre)
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]