# transactions/forms.py
from django import forms

from cards.models import Card

from .models import Transaction


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = [
            # ... tus campos actuales en el orden que ya uses
            "card",
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # queryset vacío por defecto, y si viene user filtramos
        qs = Card.objects.none()
        if user is not None:
            qs = Card.objects.filter(user=user).order_by("name")

        self.fields["card"].queryset = qs
        self.fields["card"].required = False