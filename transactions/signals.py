# transactions/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from budgets.notifications import handle_new_transaction

from .models import Transaction


@receiver(post_save, sender=Transaction)
def on_transaction_created(sender, instance: Transaction, created: bool, **kwargs):
    if not created:
        return
    handle_new_transaction(instance)