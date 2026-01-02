from __future__ import annotations

from django.contrib import admin

from .models import Loan, LoanAlertLog, LoanInstallment


class LoanInstallmentInline(admin.TabularInline):
    model = LoanInstallment
    extra = 0
    fields = ("n", "due_date", "amount_original", "currency_original", "amount_clp", "status", "paid_at")
    readonly_fields = ()
    ordering = ("n",)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "direction",
        "person_name",
        "principal_original",
        "currency_original",
        "principal_clp",
        "installments_count",
        "frequency",
        "first_due_date",
        "status",
        "created_at",
    )
    list_filter = ("direction", "status", "currency_original", "frequency")
    search_fields = ("person_name", "user__username", "user__email")
    ordering = ("-id",)
    inlines = [LoanInstallmentInline]
    actions = ["action_build_installments"]

    @admin.action(description="Crear/Recrear cuotas (si no hay pagadas)")
    def action_build_installments(self, request, queryset):
        total_created = 0
        for loan in queryset:
            total_created += loan.build_installments(replace_if_safe=True)
        self.message_user(request, f"Cuotas creadas: {total_created}")


@admin.register(LoanInstallment)
class LoanInstallmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "loan",
        "n",
        "due_date",
        "amount_original",
        "currency_original",
        "amount_clp",
        "status",
        "paid_at",
        "updated_at",
    )
    list_filter = ("status", "currency_original")
    search_fields = ("loan__person_name", "loan__user__username", "loan__user__email")
    ordering = ("-due_date", "-id")


@admin.register(LoanAlertLog)
class LoanAlertLogAdmin(admin.ModelAdmin):
    list_display = ("id", "installment", "alert_type", "channel", "sent_at")
    list_filter = ("alert_type", "channel")
    ordering = ("-sent_at",)