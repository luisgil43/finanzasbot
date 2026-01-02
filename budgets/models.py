# budgets/models.py
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def month_start(d):
    """Normaliza una fecha al primer día del mes."""
    if not d:
        d = timezone.localdate()
    return d.replace(day=1)


class BudgetCategory(models.Model):
    """
    Categoría de presupuesto por usuario.

    NOTA MVP:
    Como Transaction aún no tiene categoría, usamos keywords (coma-separadas)
    para estimar el gasto de la categoría por descripción.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_categories")

    name = models.CharField(max_length=64)
    # keywords: "uber, transporte, bencina"
    match_keywords = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Palabras clave separadas por coma para estimar gasto por descripción."),
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Budget category")
        verbose_name_plural = _("Budget categories")
        unique_together = [("user", "name")]
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return f"{self.name}"

    def keywords_list(self):
        raw = (self.match_keywords or "").strip()
        if not raw:
            return []
        parts = [p.strip() for p in raw.split(",")]
        return [p for p in parts if p]


class MonthlyBudget(models.Model):
    """
    Presupuesto mensual por categoría (por usuario).
    Guardamos month como primer día del mes (YYYY-MM-01).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monthly_budgets")
    category = models.ForeignKey(BudgetCategory, on_delete=models.CASCADE, related_name="monthly_budgets")

    month = models.DateField(default=month_start)  # siempre YYYY-MM-01
    amount_clp = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal("0"))

    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Monthly budget")
        verbose_name_plural = _("Monthly budgets")
        unique_together = [("user", "category", "month")]
        ordering = ["-month", "category__name", "-id"]

    def __str__(self) -> str:
        return f"{self.user_id} {self.month} {self.category.name}"

    def clean(self):
        # asegurar primer día del mes
        if self.month:
            self.month = month_start(self.month)


class BudgetAlertState(models.Model):
    LEVELS = (
        ("none", "none"),
        ("near80", "near80"),
        ("over", "over"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.ForeignKey("budgets.BudgetCategory", on_delete=models.CASCADE)
    month = models.DateField()

    last_level = models.CharField(max_length=16, choices=LEVELS, default="none")
    last_over_amount = models.IntegerField(default=0)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("user", "category", "month"),)

    def __str__(self):
        return f"{self.user_id} {self.category_id} {self.month} {self.last_level}"