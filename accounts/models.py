# accounts/models.py
from django.conf import settings
from django.db import models
from django.db.models import Q


class UserProfile(models.Model):
    CURRENCY_CHOICES = (
        ("CLP", "CLP"),
        ("USD", "USD"),
    )
    LANGUAGE_CHOICES = (
        ("es", "Español"),
        ("en", "English"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    # Preferencias
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="CLP")
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default="es")
    email_verified = models.BooleanField(default=False)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True)

    # Telegram
    telegram_user_id = models.CharField(max_length=32, blank=True, null=True)  # 👈 ya NO unique=True
    telegram_username = models.CharField(max_length=64, blank=True, null=True)

    # Código para vincular Telegram desde web -> /start CODE
    telegram_link_code = models.CharField(max_length=64, blank=True, null=True)  # 👈 ya NO unique=True

    # ✅ NUEVO: Fecha de nacimiento (para analytics por rango de edad)
    birth_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # ÚNICO solo si hay valor (no NULL y no "")
            models.UniqueConstraint(
                fields=["telegram_user_id"],
                name="uniq_userprofile_telegram_user_id_when_present",
                condition=Q(telegram_user_id__isnull=False) & ~Q(telegram_user_id=""),
            ),
            models.UniqueConstraint(
                fields=["telegram_link_code"],
                name="uniq_userprofile_telegram_link_code_when_present",
                condition=Q(telegram_link_code__isnull=False) & ~Q(telegram_link_code=""),
            ),
        ]

    def __str__(self):
        return f"Profile({self.user_id})"