from __future__ import annotations

from django.db import models
from django.utils import timezone

from accounts.models import UserProfile


class TelegramLink(models.Model):
    """
    Guarda chat_id para poder enviar alertas programadas (cuotas, presupuestos, etc.).
    No dependemos de agregar campos al UserProfile.
    """
    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name="telegram_link")
    telegram_user_id = models.BigIntegerField(db_index=True)
    telegram_chat_id = models.BigIntegerField()
    linked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["telegram_user_id"]),
        ]

    def __str__(self):
        return f"{self.profile.user} · tg_user={self.telegram_user_id} chat={self.telegram_chat_id}"


class TelegramConversation(models.Model):
    """
    Estado conversacional simple: para completar préstamos cuando faltan datos.
    """
    STATE_NONE = "none"
    STATE_LOAN_ASK_INSTALLMENTS = "loan_ask_installments"
    STATE_LOAN_ASK_FIRST_DUE = "loan_ask_first_due"

    STATE_CHOICES = (
        (STATE_NONE, "None"),
        (STATE_LOAN_ASK_INSTALLMENTS, "Loan ask installments"),
        (STATE_LOAN_ASK_FIRST_DUE, "Loan ask first due"),
    )

    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name="telegram_conversation")
    state = models.CharField(max_length=40, choices=STATE_CHOICES, default=STATE_NONE)
    payload = models.JSONField(default=dict, blank=True)  # datos parciales
    updated_at = models.DateTimeField(auto_now=True)

    def reset(self):
        self.state = self.STATE_NONE
        self.payload = {}
        self.save(update_fields=["state", "payload", "updated_at"])

    def __str__(self):
        return f"{self.profile.user} · {self.state}"