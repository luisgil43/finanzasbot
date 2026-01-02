# owner_panel/apps.py
from __future__ import annotations

from django.apps import AppConfig


class OwnerPanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "owner_panel"

    def ready(self):
        from . import signals  # noqa: F401