# config/settings/dev.py
from .base import *

DEBUG = True

ALLOWED_HOSTS = list(set(ALLOWED_HOSTS + [
    "127.0.0.1",
    "localhost",
    "192.168.1.83",
    ".trycloudflare.com",
]))

CSRF_TRUSTED_ORIGINS = list(set(CSRF_TRUSTED_ORIGINS + [
    "https://*.trycloudflare.com",
]))

# ✅ En dev permitimos console backend (si no defines EMAIL_BACKEND, imprime en consola)
setup_email(allow_console=True)