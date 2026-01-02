from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.conf import settings
from django.db import models
from django.utils import timezone


def _add_months(d: date, months: int) -> date:
    """
    Suma meses manteniendo el día cuando se puede.
    Si el mes destino no tiene ese día, cae al último día del mes.
    """
    y = d.year + ((d.month - 1 + months) // 12)
    m = ((d.month - 1 + months) % 12) + 1
    last_day = calendar.monthrange(y, m)[1]
    day = min(d.day, last_day)
    return date(y, m, day)


def _quantize_money(amount: Decimal, currency: str) -> Decimal:
    """
    CLP: sin decimales
    USD: 2 decimales
    """
    if currency == "USD":
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class Loan(models.Model):
    DIRECTION_LENT = "lent"        # yo presté (me deben)
    DIRECTION_BORROWED = "borrowed"  # me prestaron (yo debo)
    DIRECTION_CHOICES = (
        (DIRECTION_LENT, "Presté (me deben)"),
        (DIRECTION_BORROWED, "Me prestaron (yo debo)"),
    )

    FREQ_MONTHLY = "monthly"
    FREQ_WEEKLY = "weekly"
    FREQ_BIWEEKLY = "biweekly"
    FREQ_CHOICES = (
        (FREQ_MONTHLY, "Mensual"),
        (FREQ_WEEKLY, "Semanal"),
        (FREQ_BIWEEKLY, "Quincenal"),
    )

    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Activo"),
        (STATUS_CLOSED, "Cerrado"),
        (STATUS_CANCELED, "Cancelado"),
    )

    CURRENCY_CLP = "CLP"
    CURRENCY_USD = "USD"
    CURRENCY_CHOICES = (
        (CURRENCY_CLP, "CLP"),
        (CURRENCY_USD, "USD"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="loans"
    )
    direction = models.CharField(max_length=12, choices=DIRECTION_CHOICES)
    person_name = models.CharField(max_length=120)

    # Lo que el usuario escribió
    principal_original = models.DecimalField(max_digits=14, decimal_places=2)
    currency_original = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default=CURRENCY_CLP)

    # Base CLP para reportes internos
    principal_clp = models.DecimalField(max_digits=16, decimal_places=0)

    start_date = models.DateField(default=timezone.localdate)
    first_due_date = models.DateField(null=True, blank=True)

    installments_count = models.PositiveIntegerField(default=1)
    frequency = models.CharField(max_length=10, choices=FREQ_CHOICES, default=FREQ_MONTHLY)

    note = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    # trazabilidad opcional (si lo creaste desde Telegram)
    telegram_origin_message_id = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "person_name"]),
        ]
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.user} · {self.person_name} · {self.principal_original} {self.currency_original}"

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    def next_due_installment(self) -> Optional["LoanInstallment"]:
        return self.installments.filter(status=LoanInstallment.STATUS_PENDING).order_by("due_date", "n").first()

    def compute_installment_amount_original(self) -> Decimal:
        """
        Divide el principal en N cuotas con rounding apropiado por moneda.
        NOTA: el último ajuste de diferencia lo hacemos al crear cuotas.
        """
        n = max(int(self.installments_count or 1), 1)
        base = Decimal(self.principal_original) / Decimal(n)
        return _quantize_money(base, self.currency_original)

    def compute_due_date_for_n(self, n: int) -> date:
        if not self.first_due_date:
            # si no hay fecha, ponemos primer vencimiento hoy + 30 por defecto (MVP)
            first = timezone.localdate() + timedelta(days=30)
        else:
            first = self.first_due_date

        if n <= 1:
            return first

        if self.frequency == self.FREQ_WEEKLY:
            return first + timedelta(days=7 * (n - 1))
        if self.frequency == self.FREQ_BIWEEKLY:
            return first + timedelta(days=14 * (n - 1))
        # monthly
        return _add_months(first, n - 1)

    def build_installments(self, *, replace_if_safe: bool = True) -> int:
        """
        Crea cuotas automáticamente. Si replace_if_safe=True:
        - si ya existen cuotas y ninguna está pagada, las reemplaza
        - si hay alguna pagada, NO toca (para no romper historial)
        Retorna cantidad de cuotas creadas.
        """
        n_total = max(int(self.installments_count or 1), 1)

        qs = self.installments.all()
        if qs.exists():
            any_paid = qs.filter(status=LoanInstallment.STATUS_PAID).exists()
            if any_paid or not replace_if_safe:
                return 0
            qs.delete()

        currency = self.currency_original
        per = self.compute_installment_amount_original()

        # Para cuadrar exacto el total, calculamos diferencia y se la sumamos a la última cuota
        per_sum = per * Decimal(n_total)
        diff = _quantize_money(Decimal(self.principal_original) - per_sum, currency)

        created = 0
        for i in range(1, n_total + 1):
            amt = per
            if i == n_total and diff != 0:
                amt = _quantize_money(amt + diff, currency)

            LoanInstallment.objects.create(
                loan=self,
                n=i,
                due_date=self.compute_due_date_for_n(i),
                amount_original=amt,
                currency_original=currency,
                amount_clp=self._amount_original_to_clp(amt, currency),
                status=LoanInstallment.STATUS_PENDING,
            )
            created += 1

        return created

    def _amount_original_to_clp(self, amount: Decimal, currency: str) -> Decimal:
        """
        Por ahora: si USD, se asume que ya convertiste principal_clp correctamente.
        Para cuotas, aproximamos proporcionalmente al principal.
        (Luego lo refinamos usando fx_rate histórico por cuota si quieres.)
        """
        amount = Decimal(amount)
        if currency == self.CURRENCY_CLP:
            return _quantize_money(amount, "CLP")

        # proporcional al principal
        if self.principal_original and Decimal(self.principal_original) != 0:
            ratio = amount / Decimal(self.principal_original)
            approx = Decimal(self.principal_clp) * ratio
            return _quantize_money(approx, "CLP")

        return Decimal("0")


class LoanInstallment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_OVERDUE = "overdue"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pendiente"),
        (STATUS_PAID, "Pagada"),
        (STATUS_OVERDUE, "Atrasada"),
    )

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="installments")

    n = models.PositiveIntegerField()
    due_date = models.DateField()

    amount_original = models.DecimalField(max_digits=14, decimal_places=2)
    currency_original = models.CharField(max_length=3, choices=Loan.CURRENCY_CHOICES, default=Loan.CURRENCY_CLP)
    amount_clp = models.DecimalField(max_digits=16, decimal_places=0)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)

    paid_at = models.DateTimeField(null=True, blank=True)
    paid_amount_original = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    paid_amount_clp = models.DecimalField(max_digits=16, decimal_places=0, null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("loan", "n"),)
        indexes = [
            models.Index(fields=["loan", "status"]),
            models.Index(fields=["due_date", "status"]),
        ]
        ordering = ("due_date", "n")

    def __str__(self) -> str:
        return f"{self.loan_id} · cuota {self.n} · {self.amount_original} {self.currency_original} · {self.status}"

    def refresh_overdue_status(self) -> bool:
        """
        Marca como atrasada si corresponde (sin tocar pagadas).
        Retorna True si cambió.
        """
        if self.status == self.STATUS_PAID:
            return False

        today = timezone.localdate()
        should = self.STATUS_OVERDUE if self.due_date < today else self.STATUS_PENDING
        if self.status != should:
            self.status = should
            self.save(update_fields=["status", "updated_at"])
            return True
        return False


class LoanAlertLog(models.Model):
    ALERT_DUE_TODAY = "due_today"
    ALERT_DUE_SOON = "due_soon"      # ej: vence en 3 días
    ALERT_OVERDUE = "overdue"
    ALERT_CHOICES = (
        (ALERT_DUE_TODAY, "Vence hoy"),
        (ALERT_DUE_SOON, "Vence pronto"),
        (ALERT_OVERDUE, "Atrasada"),
    )

    CHANNEL_TELEGRAM = "telegram"
    CHANNEL_EMAIL = "email"
    CHANNEL_CHOICES = (
        (CHANNEL_TELEGRAM, "Telegram"),
        (CHANNEL_EMAIL, "Email"),
    )

    installment = models.ForeignKey(LoanInstallment, on_delete=models.CASCADE, related_name="alert_logs")
    alert_type = models.CharField(max_length=20, choices=ALERT_CHOICES)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=CHANNEL_TELEGRAM)

    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["installment", "alert_type", "channel"]),
            models.Index(fields=["sent_at"]),
        ]
        ordering = ("-sent_at",)

    def __str__(self) -> str:
        return f"{self.installment_id} · {self.alert_type} · {self.channel} · {self.sent_at:%Y-%m-%d %H:%M}"
    

