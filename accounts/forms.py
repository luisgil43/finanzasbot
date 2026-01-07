# accounts/forms.py
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

UserModel = get_user_model()


class SignUpForm(UserCreationForm):
    first_name = forms.CharField(
        required=True,
        max_length=150,
        label="Nombre",
    )
    last_name = forms.CharField(
        required=True,
        max_length=150,
        label="Apellido",
    )
    birth_date = forms.DateField(
        required=True,
        label="Fecha de nacimiento",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    email = forms.EmailField(required=True, label="Email")

    class Meta(UserCreationForm.Meta):
        model = UserModel
        fields = ("username", "first_name", "last_name", "birth_date", "email", "password1", "password2")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("Debes ingresar un correo.")
        if UserModel.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Este correo ya está registrado. Inicia sesión o revisa tu verificación.")
        return email

    def clean_first_name(self):
        v = (self.cleaned_data.get("first_name") or "").strip()
        if not v:
            raise forms.ValidationError("Debes ingresar tu nombre.")
        return v

    def clean_last_name(self):
        v = (self.cleaned_data.get("last_name") or "").strip()
        if not v:
            raise forms.ValidationError("Debes ingresar tu apellido.")
        return v

    def save(self, commit=True):
        user = super().save(commit=False)

        user.email = (self.cleaned_data.get("email") or "").strip().lower()
        user.first_name = (self.cleaned_data.get("first_name") or "").strip()
        user.last_name = (self.cleaned_data.get("last_name") or "").strip()

        if commit:
            user.save()
        return user