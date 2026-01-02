from django.contrib import admin

from .models import BillingSettings, Plan, UserSubscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "name", "is_active", "price_monthly_clp")
    list_filter = ("is_active", "code")
    search_fields = ("code", "name")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "plan", "status", "started_at", "ends_at")
    list_filter = ("status", "plan")
    search_fields = ("user__username", "user__email", "plan__code")


@admin.register(BillingSettings)
class BillingSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "business_name", "billing_email", "currency_default", "updated_at")
    search_fields = ("owner__username", "owner__email", "business_name", "billing_email")