# config/settings/prod.py
from .base import *

DEBUG = False

# En PROD normalmente lo defines por env DJANGO_ALLOWED_HOSTS
# ALLOWED_HOSTS ya viene de env en base.py

# En PROD exigimos backend (console NO)
if not EMAIL_BACKEND:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# Si queda en SMTP, base.py ya obliga EMAIL_HOST/USER/PASSWORD/PORT por env

# Seguridad típica prod (puedes controlar por env si quieres)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", True)

# Si estás detrás de proxy (Render), esto ayuda
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")