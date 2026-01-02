# transactions/admin.py
from django.contrib import admin
from django.db.models import Field

from .models import Transaction


def _model_field_names(model):
    names = set()
    for f in model._meta.get_fields():
        if isinstance(f, Field):
            names.add(f.name)
    return names


class CurrencySmartFilter(admin.SimpleListFilter):
    title = "Currency"
    parameter_name = "currency"

    def lookups(self, request, model_admin):
        return [
            ("CLP", "CLP"),
            ("USD", "USD"),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if not val:
            return queryset

        fields = _model_field_names(Transaction)

        # nombres soportados (incluye el nuevo)
        for fname in ("currency_original", "currency", "original_currency", "currency_code"):
            if fname in fields:
                return queryset.filter(**{fname: val})

        return queryset


class SourceSmartFilter(admin.SimpleListFilter):
    title = "Source"
    parameter_name = "src"

    def lookups(self, request, model_admin):
        # Puedes ajustar a tus valores reales
        return [
            ("telegram", "telegram"),
            ("web", "web"),
            ("mindicador", "mindicador"),
            ("base", "base"),
            ("cache", "cache"),
            ("default", "default"),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if not val:
            return queryset

        fields = _model_field_names(Transaction)

        # si existe fuente de FX
        if "fx_source" in fields:
            return queryset.filter(fx_source=val)

        # si existe source clásico (origen del registro)
        if "source" in fields:
            return queryset.filter(source=val)

        return queryset


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "kind",
        "amount_clp_display",
        "amount_original_display",
        "currency_original_display",
        "occurred_at",
        "source_display",
        "telegram_message_id",
        "created_at",
    )
    list_select_related = ("user",)
    ordering = ("-occurred_at", "-id")
    search_fields = ("user__username", "user__email", "description")
    list_filter = ("kind", CurrencySmartFilter, SourceSmartFilter)

    @admin.display(description="Amount (CLP base)")
    def amount_clp_display(self, obj: Transaction):
        for attr in ("amount_clp", "amount_base", "amount"):
            if hasattr(obj, attr):
                v = getattr(obj, attr)
                if v is not None:
                    return v
        return "—"

    @admin.display(description="Amount (original)")
    def amount_original_display(self, obj: Transaction):
        for attr in ("amount_original",):
            if hasattr(obj, attr):
                v = getattr(obj, attr)
                if v is not None:
                    return v
        # fallback por compatibilidad
        for attr in ("amount",):
            if hasattr(obj, attr):
                v = getattr(obj, attr)
                if v is not None:
                    return v
        return "—"

    @admin.display(description="Currency (original)")
    def currency_original_display(self, obj: Transaction):
        for attr in ("currency_original", "currency", "original_currency", "currency_code"):
            if hasattr(obj, attr):
                v = getattr(obj, attr)
                if v:
                    return v
        return "—"

    @admin.display(description="Source")
    def source_display(self, obj: Transaction):
        # muestra fx_source si existe, o source si existe
        if hasattr(obj, "fx_source") and obj.fx_source:
            return obj.fx_source
        if hasattr(obj, "source") and obj.source:
            return obj.source
        return "—"