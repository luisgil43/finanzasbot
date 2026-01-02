# config/settings/dev.py
from .base import *

DEBUG = True

ALLOWED_HOSTS = list(set(ALLOWED_HOSTS + [
    "127.0.0.1",
    "localhost",
    ".trycloudflare.com",
]))

CSRF_TRUSTED_ORIGINS = list(set(CSRF_TRUSTED_ORIGINS + [
    "https://*.trycloudflare.com",
]))

# DEV: permitimos console backend (si no defines EMAIL_BACKEND)
setup_email(allow_console=True)