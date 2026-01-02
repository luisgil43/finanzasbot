from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _  # ✅ FALTABA


class Transaction(models.Model):
    KIND_EXPENSE = "expense"
    KIND_INCOME = "income"

    KIND_CHOICES = (
        (KIND_EXPENSE, _("Gasto")),
        (KIND_INCOME, _("Ingreso")),
    )

    CURRENCY_CHOICES = (
        ("CLP", "CLP"),
        ("USD", "USD"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transactions",
    )

    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_EXPENSE)

    # Lo que el usuario ingresó (en su moneda)
    amount_original = models.DecimalField(max_digits=14, decimal_places=2)
    currency_original = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="CLP")

    # Normalizado SIEMPRE a CLP (moneda base)
    amount_clp = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))

    # Info FX usada para normalizar
    fx_rate = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("1"))
    fx_source = models.CharField(max_length=30, default="default")
    fx_timestamp = models.DateTimeField(null=True, blank=True)

    description = models.CharField(max_length=255, blank=True)

    # tracking (Telegram / web)
    source = models.CharField(max_length=20, default="telegram")
    telegram_message_id = models.BigIntegerField(null=True, blank=True)

    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    # ✅ FK a Tarjeta (cards)
    card = models.ForeignKey(
        "cards.Card",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="Tarjeta",
    )

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["user", "occurred_at"]),
            models.Index(fields=["user", "kind", "occurred_at"]),
            models.Index(fields=["user", "currency_original", "occurred_at"]),
            models.Index(fields=["user", "card", "occurred_at"]),  # ✅ útil para Cards
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.kind} {self.amount_original} {self.currency_original} => {self.amount_clp} CLP"