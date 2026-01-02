"""
WSGI config for config project.
"""

import os

from django.core.wsgi import get_wsgi_application

# ✅ Respeta env, si no existe usa prod por defecto
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.prod"),
)

application = get_wsgi_application()