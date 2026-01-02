from .base import *

DEBUG = True

# En DEV aceptamos tu LAN + cualquier quick tunnel
ALLOWED_HOSTS = list(set(ALLOWED_HOSTS + [
    "127.0.0.1",
    "localhost",
    "192.168.1.83",
    ".trycloudflare.com",
]))

# Si vas a usar el admin / forms desde el tunnel (no aplica a webhook porque es csrf_exempt)
CSRF_TRUSTED_ORIGINS = list(set(CSRF_TRUSTED_ORIGINS + [
    "https://*.trycloudflare.com",
]))