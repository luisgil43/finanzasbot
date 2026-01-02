from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Card(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cards",
        verbose_name=_("Usuario"),
    )

    name = models.CharField(_("Nombre"), max_length=80)
    bank = models.CharField(_("Banco"), max_length=80, blank=True, default="")
    brand = models.CharField(_("Marca"), max_length=40, blank=True, default="")
    last4 = models.CharField(_("Últimos 4"), max_length=4, blank=True, default="")

    currency = models.CharField(_("Moneda"), max_length=10, default="CLP")
    credit_limit = models.DecimalField(
        _("Límite / cupo"),
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    billing_day = models.PositiveSmallIntegerField(
        _("Día de corte"),
        default=1,
        help_text=_("Día del mes en que inicia el ciclo (corte). Ej: 5, 10, 25."),
    )
    due_day = models.PositiveSmallIntegerField(
        _("Día de pago"),
        default=1,
        help_text=_("Día del mes en que pagas la tarjeta. Ej: 1, 15, 28."),
    )

    is_active = models.BooleanField(_("Activa"), default=True)

    created_at = models.DateTimeField(_("Creada"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Actualizada"), auto_now=True)

    class Meta:
        verbose_name = _("Tarjeta")
        verbose_name_plural = _("Tarjetas")
        ordering = ["-is_active", "name"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        suffix = f" • ****{self.last4}" if self.last4 else ""
        return f"{self.name}{suffix}"

    def clean(self):
        # Validaciones suaves (Django admin/forms)
        if self.billing_day < 1 or self.billing_day > 31:
            raise ValueError("billing_day must be between 1 and 31")
        if self.due_day < 1 or self.due_day > 31:
            raise ValueError("due_day must be between 1 and 31")

    # ---- Helpers de ciclo ----
    def cycle_start_for(self, d: date) -> date:
        """
        Retorna el inicio del ciclo que contiene la fecha d, usando billing_day.
        Regla:
          - si d.day >= billing_day => ciclo inicia el mismo mes en billing_day
          - si d.day < billing_day  => ciclo inicia el mes anterior en billing_day
        Nota: si el mes no tiene ese día (ej 31 en Feb), se ajusta al último día del mes.
        """
        def clamp_day(year: int, month: int, day_num: int) -> date:
            # último día del mes: ir al 1 del mes siguiente y restar 1
            if month == 12:
                last = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last = date(year, month + 1, 1) - timedelta(days=1)
            day_num = min(day_num, last.day)
            return date(year, month, day_num)

        if d.day >= self.billing_day:
            return clamp_day(d.year, d.month, self.billing_day)

        # mes anterior
        if d.month == 1:
            return clamp_day(d.year - 1, 12, self.billing_day)
        return clamp_day(d.year, d.month - 1, self.billing_day)

    def cycle_end_for(self, d: date) -> date:
        """
        Fin del ciclo (inclusive) para la fecha d: el día anterior al próximo ciclo start.
        """
        start = self.cycle_start_for(d)
        # next month relative to start
        year, month = start.year, start.month
        if month == 12:
            next_month_year, next_month = year + 1, 1
        else:
            next_month_year, next_month = year, month + 1

        # el siguiente start (clamp) y restamos 1 día
        tmp = Card(
            billing_day=self.billing_day,
            due_day=self.due_day,
        )
        next_start = tmp.cycle_start_for(date(next_month_year, next_month, 28))  # seed
        # pero queremos next_start = clamp_day(next_month_year, next_month, billing_day)
        # reusamos lógica usando cycle_start_for con un día >= billing_day
        d_seed = date(next_month_year, next_month, min(28, self.billing_day if self.billing_day <= 28 else 28))
        next_start = tmp.cycle_start_for(d_seed).replace(day=min(tmp.cycle_start_for(d_seed).day, tmp.cycle_start_for(d_seed).day))
        # lo anterior es redundante, mejor calc directo:
        # (mantengo simple abajo con el clamp)
        def clamp_day(year: int, month: int, day_num: int) -> date:
            if month == 12:
                last = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last = date(year, month + 1, 1) - timedelta(days=1)
            return date(year, month, min(day_num, last.day))

        next_start = clamp_day(next_month_year, next_month, self.billing_day)
        return next_start - timedelta(days=1)

    def current_cycle_range(self) -> tuple[date, date]:
        today = timezone.localdate()
        return self.cycle_start_for(today), self.cycle_end_for(today)


@dataclass(frozen=True)
class CardCycleInfo:
    start: date
    end: date
    spent: Decimal
    available: Decimal