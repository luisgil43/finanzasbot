from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone

from cards.models import Card


class ReceiptUploadForm(forms.Form):
    image = forms.ImageField()


class ReceiptConfirmForm(forms.Form):
    kind = forms.ChoiceField(choices=(("expense", "Gasto"), ("income", "Ingreso")), initial="expense")
    amount = forms.CharField()
    currency = forms.ChoiceField(choices=(("CLP", "CLP"), ("USD", "USD")), initial="CLP")
    occurred_date = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    description = forms.CharField(required=False)
    card_id = forms.ChoiceField(required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # cards dropdown (0 = sin tarjeta)
        choices = [("", "Sin tarjeta")]
        if user:
            cards = Card.objects.filter(user=user, is_active=True).order_by("name", "id")[:50]
            for c in cards:
                label = " · ".join([p for p in [str(getattr(c, "name", "") or "").strip(),
                                               str(getattr(c, "bank", "") or "").strip(),
                                               str(getattr(c, "brand", "") or "").strip(),
                                               (f"****{getattr(c, 'last4', '')}" if getattr(c, "last4", "") else "").strip()] if p])
                choices.append((str(c.id), label))
        self.fields["card_id"].choices = choices

    def clean_amount(self) -> Decimal:
        raw = (self.cleaned_data.get("amount") or "").strip()
        if not raw:
            raise forms.ValidationError("Indica el monto.")
        # normaliza miles
        txt = raw.replace(" ", "")
        txt = txt.replace(".", "").replace(",", ".")
        try:
            val = Decimal(txt)
        except (InvalidOperation, ValueError):
            raise forms.ValidationError("Monto inválido.")
        if val <= 0:
            raise forms.ValidationError("El monto debe ser mayor a 0.")
        return val