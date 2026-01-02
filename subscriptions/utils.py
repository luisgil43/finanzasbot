from __future__ import annotations

from django.utils import timezone

from subscriptions.features import DEFAULT_PLANS
from subscriptions.models import Plan, UserSubscription


def get_active_subscription(user) -> UserSubscription | None:
    now = timezone.now()
    sub = (
        UserSubscription.objects.select_related("plan")
        .filter(user=user, status=UserSubscription.STATUS_ACTIVE)
        .order_by("-started_at", "-id")
        .first()
    )
    if not sub:
        return None

    if sub.ends_at and sub.ends_at <= now:
        sub.status = UserSubscription.STATUS_EXPIRED
        sub.save(update_fields=["status"])
        return None

    if not sub.plan.is_active:
        return None

    return sub


def get_user_plan_code(user) -> str:
    sub = get_active_subscription(user)
    if sub and sub.plan and sub.plan.code:
        return sub.plan.code
    return Plan.CODE_FREE


def has_feature(user, feature_key: str) -> bool:
    plan_code = get_user_plan_code(user)
    defaults = DEFAULT_PLANS.get(plan_code, DEFAULT_PLANS["free"])

    sub = get_active_subscription(user)
    if sub and sub.plan and isinstance(sub.plan.features, dict) and sub.plan.features:
        merged = dict(defaults)
        merged.update(sub.plan.features)
        return bool(merged.get(feature_key, False))

    return bool(defaults.get(feature_key, False))