# config/settings/base.py
from __future__ import annotations

import os
from pathlib import Path

from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # .../finanzas_bot

# -----------------------
# Helpers
# -----------------------
def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)

def env_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

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

# -----------------------
# Local .env loader (DEV)
# -----------------------
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

# -----------------------
# Core
# -----------------------
SECRET_KEY = env_required("DJANGO_SECRET_KEY")

# DEBUG lo define cada settings (dev/prod)
DEBUG = False

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost", "192.168.1.83"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# -----------------------
# Application definition
# -----------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Local apps
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

# -----------------------
# Database
# -----------------------
DATABASE_URL = env("DATABASE_URL")

if DATABASE_URL:
    try:
        import dj_database_url
        DATABASES = {
            "default": dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=not DEBUG)
        }
    except Exception as e:
        raise RuntimeError(
            "DATABASE_URL está definido pero falta 'dj-database-url' "
            f"o hubo error parseando: {e}"
        )
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# -----------------------
# Password validation
# -----------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------
# i18n / timezone
# -----------------------
USE_I18N = True
USE_TZ = True

LANGUAGE_CODE = "es"
LANGUAGES = [
    ("es", _("Español")),
    ("en", _("English")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "America/Santiago"

# -----------------------
# Static
# -----------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------
# Email (se configura en dev/prod llamando setup_email)
# -----------------------
SITE_URL: str
DEFAULT_FROM_EMAIL: str
EMAIL_BACKEND: str

def setup_email(*, allow_console: bool) -> None:
    """
    Configura email de forma correcta según el entorno.
    - En DEV permitimos console backend (imprime en logs).
    - En PROD lo prohibimos: si queda console, levantamos error.
    """
    global SITE_URL, DEFAULT_FROM_EMAIL, EMAIL_BACKEND
    global EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_TIMEOUT

    SITE_URL = env_required("SITE_URL").rstrip("/")
    DEFAULT_FROM_EMAIL = env_required("DEFAULT_FROM_EMAIL").strip()

    EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "20"))

    raw_backend = (env("EMAIL_BACKEND") or "").strip()
    if raw_backend:
        EMAIL_BACKEND = raw_backend
    else:
        EMAIL_BACKEND = (
            "django.core.mail.backends.console.EmailBackend"
            if allow_console
            else "django.core.mail.backends.smtp.EmailBackend"
        )

    # En PROD NO permitimos console/locmem/dummy
    if not allow_console and EMAIL_BACKEND in (
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    ):
        raise RuntimeError(
            "EMAIL_BACKEND está en modo DEV (console/locmem/dummy). "
            "En producción debes usar SMTP: django.core.mail.backends.smtp.EmailBackend"
        )

    # Si es SMTP, exigimos variables
    if EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend":
        EMAIL_HOST = env_required("EMAIL_HOST")
        EMAIL_PORT = int(env_required("EMAIL_PORT"))
        EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
        EMAIL_HOST_USER = env_required("EMAIL_HOST_USER")
        EMAIL_HOST_PASSWORD = env_required("EMAIL_HOST_PASSWORD")

# -----------------------
# Telegram (SIEMPRE env)
# -----------------------
TELEGRAM_BOT_TOKEN = env_required("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = env_required("TELEGRAM_BOT_USERNAME")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", "")

# -----------------------
# Auth redirects
# -----------------------
LOGIN_URL = "/usuarios/login/"
LOGIN_REDIRECT_URL = "/usuarios/"
LOGOUT_REDIRECT_URL = "/usuarios/login/"