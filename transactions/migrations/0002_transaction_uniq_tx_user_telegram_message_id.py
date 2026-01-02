# transactions/migrations/0002_transaction_base_clp.py
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="base_currency",
            field=models.CharField(default="CLP", max_length=3),
        ),
        migrations.AddField(
            model_name="transaction",
            name="fx_rate",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="transaction",
            name="amount_base",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("telegram_message_id__isnull", False)),
                fields=("user", "telegram_message_id"),
                name="uniq_transaction_user_telegram_msg",
            ),
        ),
    ]