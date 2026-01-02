# config/settings/base.py
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)

def env_required(name: str) -> str:
    v = os.getenv(name)
    if not v or not v.strip():
        raise RuntimeError(f"Missing required env var: {name}")
    return v.strip()

def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "t", "yes", "y", "on")

def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return default or []
    return [x.strip() for x in raw.split(",") if x.strip()]

def env_str_or_default(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw if raw else default

def _looks_falsey(s: str) -> bool:
    return (s or "").strip().lower() in ("false", "0", "none", "null", "no", "off", "")

def normalize_smtp_host(host: str) -> tuple[str, int | None]:
    h = (host or "").strip()
    if not h:
        return "", None

    # URL smtp://...
    if "://" in h:
        u = urlparse(h)
        return (u.hostname or "").strip(), u.port

    # host:port
    if ":" in h and h.count(":") == 1:
        left, right = h.split(":", 1)
        left = left.strip()
        right = right.strip()
        if right.isdigit():
            return left, int(right)

    return h, None


try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass


SECRET_KEY = env_required("DJANGO_SECRET_KEY")
DEBUG = False

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "accounts.apps.AccountsConfig",
    "subscriptions",
    "bot_telegram",
    "owner_panel.apps.OwnerPanelConfig",
    "budgets",
    "cards",
    "transactions",
    "loans",
    "ocr_receipts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",

    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASE_URL = env("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=not DEBUG)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

USE_I18N = True
USE_TZ = True

LANGUAGE_CODE = "es"
LANGUAGES = [("es", _("Español")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "America/Santiago"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# -----------------------
# ✅ EMAIL (modo GZ: solo user/pass obligatorios) + auto SSL/TLS según puerto
# -----------------------
SITE_URL = env_required("SITE_URL").rstrip("/")

EMAIL_BACKEND = env_str_or_default("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")

raw_host = env_str_or_default("EMAIL_HOST", "mail.grupogzs.com")
# Si Render te mete "false" o basura, lo ignoramos
if _looks_falsey(raw_host):
    raw_host = "mail.grupogzs.com"

host_clean, port_override = normalize_smtp_host(raw_host)
EMAIL_HOST = host_clean or "mail.grupogzs.com"

EMAIL_PORT = int(env_str_or_default("EMAIL_PORT", "465"))
if port_override:
    EMAIL_PORT = port_override

# Credenciales (mínimo)
EMAIL_HOST_USER = (os.environ.get("EMAIL_HOST_USER") or "").strip()
EMAIL_HOST_PASSWORD = (os.environ.get("EMAIL_HOST_PASSWORD") or "").strip()

DEFAULT_FROM_EMAIL = env_str_or_default("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "planix@grupogzs.com")

# Auto modo según puerto (evita el error de mutually exclusive)
if EMAIL_PORT == 465:
    EMAIL_USE_SSL = True
    EMAIL_USE_TLS = False
elif EMAIL_PORT == 587:
    EMAIL_USE_SSL = False
    EMAIL_USE_TLS = True
else:
    # fallback configurable
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
    if EMAIL_USE_SSL and EMAIL_USE_TLS:
        # preferimos SSL si ambos vinieron true
        EMAIL_USE_TLS = False

if EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend":
    if not EMAIL_HOST_USER:
        raise RuntimeError("Missing required env var: EMAIL_HOST_USER")
    if not EMAIL_HOST_PASSWORD:
        raise RuntimeError("Missing required env var: EMAIL_HOST_PASSWORD")


# -----------------------
# Telegram
# -----------------------
TELEGRAM_BOT_TOKEN = env_required("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = env_required("TELEGRAM_BOT_USERNAME")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", "") or ""


LOGIN_URL = "/usuarios/login/"
LOGIN_REDIRECT_URL = "/usuarios/"
LOGOUT_REDIRECT_URL = "/usuarios/login/"