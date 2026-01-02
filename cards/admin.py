from django.contrib import admin

from .models import Card


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "bank", "brand", "last4", "currency", "credit_limit", "billing_day", "due_day", "is_active")
    list_filter = ("is_active", "currency", "billing_day", "due_day")
    search_fields = ("name", "bank", "brand", "last4", "user__username", "user__email")