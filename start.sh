#!/usr/bin/env bash
set -euo pipefail

# Asegura que manage.py use PROD en Render (y puedas overridear por env si quieres)
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting gunicorn..."
# Render inyecta $PORT automáticamente
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${WEB_CONCURRENCY:-2} \
  --timeout 120