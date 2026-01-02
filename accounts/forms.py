# accounts/forms.py
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

UserModel = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = UserModel
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("Debes ingresar un correo.")
        if UserModel.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Este correo ya está registrado. Inicia sesión o revisa tu verificación.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = (self.cleaned_data.get("email") or "").strip().lower()
        if commit:
            user.save()
        return user