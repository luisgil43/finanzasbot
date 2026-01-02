from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class ReceiptUpload(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PARSED = "parsed"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELED = "canceled"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PARSED, "Parsed"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_FAILED, "Failed"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="receipt_uploads")
    image = models.ImageField(upload_to="receipts/%Y/%m/%d/")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    ocr_text = models.TextField(blank=True, default="")

    # Campos sugeridos por OCR (editables en confirmación)
    suggested_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    suggested_currency = models.CharField(max_length=3, default="CLP")
    suggested_date = models.DateField(null=True, blank=True)
    suggested_merchant = models.CharField(max_length=255, blank=True, default="")
    suggested_description = models.CharField(max_length=255, blank=True, default="")

    # Resultado final (cuando se confirma)
    confirmed_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    confirmed_currency = models.CharField(max_length=3, blank=True, default="")
    confirmed_date = models.DateField(null=True, blank=True)
    confirmed_description = models.CharField(max_length=255, blank=True, default="")
    confirmed_card = models.ForeignKey("cards.Card", on_delete=models.SET_NULL, null=True, blank=True)
    created_transaction = models.ForeignKey("transactions.Transaction", on_delete=models.SET_NULL, null=True, blank=True)

    error = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"ReceiptUpload #{self.id} ({self.user_id}) {self.status}"