from decimal import Decimal, InvalidOperation

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Card


class CardForm(forms.ModelForm):
    class Meta:
        model = Card
        fields = [
            "name", "bank", "brand", "last4",
            "currency", "credit_limit",
            "billing_day", "due_day",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm"}),
            "bank": forms.TextInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm"}),
            "brand": forms.TextInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm"}),
            "last4": forms.TextInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm", "maxlength": "4"}),
            "currency": forms.TextInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm"}),
            "credit_limit": forms.TextInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm", "placeholder": _("Ej: 800.000")}),
            "billing_day": forms.NumberInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm", "min": "1", "max": "31"}),
            "due_day": forms.NumberInput(attrs={"class": "w-full rounded-xl bg-slate-950/40 border border-white/10 px-3 py-2 text-sm", "min": "1", "max": "31"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4"}),
        }

    def clean_last4(self):
        last4 = (self.cleaned_data.get("last4") or "").strip()
        if last4 and (not last4.isdigit() or len(last4) != 4):
            raise forms.ValidationError(_("Últimos 4 debe ser un número de 4 dígitos."))
        return last4

    def clean_credit_limit(self):
        raw = str(self.cleaned_data.get("credit_limit") or "").strip()
        if raw == "":
            return Decimal("0.00")

        # permitir puntos de miles
        txt = raw.replace(".", "").replace(",", ".")
        try:
            return Decimal(txt)
        except (InvalidOperation, ValueError):
            raise forms.ValidationError(_("Monto inválido."))