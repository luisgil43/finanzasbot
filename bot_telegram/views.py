# bot_telegram/views.py
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import handle_incoming_telegram_update

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": True})

    try:
        handle_incoming_telegram_update(payload)
    except Exception as e:
        # no queremos romper el webhook por una excepción
        logger.exception("Telegram webhook error: %s", e)

    return JsonResponse({"ok": True})