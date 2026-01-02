from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.Model):
    """
    Plan comercial.
    """
    CODE_FREE = "free"
    CODE_PLUS = "plus"
    CODE_PRO = "pro"

    CODE_CHOICES = (
        (CODE_FREE, "Free"),
        (CODE_PLUS, "Plus"),
        (CODE_PRO, "Pro"),
    )

    code = models.CharField(max_length=20, choices=CODE_CHOICES, unique=True)
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)

    # opcional (referencial)
    price_monthly_clp = models.PositiveIntegerField(default=0)

    # feature flags (override)
    features = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class UserSubscription(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_CANCELED = "canceled"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_EXPIRED, "Expired"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    started_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.plan.code} ({self.status})"


class BillingSettings(models.Model):
    """
    Settings de facturación/comercialización para el Owner Panel.
    Lo dejo simple para que NO rompa lo actual.

    Si más adelante conectas Stripe/Flow/MercadoPago, lo extendemos aquí.
    """
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing_settings",
    )

    business_name = models.CharField(max_length=160, blank=True, default="")
    tax_id = models.CharField(max_length=40, blank=True, default="")  # RUT/NIF/etc
    billing_email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=60, blank=True, default="")

    billing_enabled = models.BooleanField(default=False)
    go_live_date = models.DateField(null=True, blank=True)
    address_line = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    country = models.CharField(max_length=80, blank=True, default="CL")

    currency_default = models.CharField(max_length=3, default="CLP")

    # Config extra (pasarela, ids, flags)
    config = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["owner"]),
        ]

    def __str__(self) -> str:
        return f"BillingSettings({self.owner})"