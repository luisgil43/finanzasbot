# bot_telegram/services.py
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional, Tuple

import requests
from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import UserProfile
from cards.models import Card
from loans.models import Loan
from subscriptions.features import FEATURE_LOAN_ALERTS, FEATURE_TX_QUERY_RANGE
from subscriptions.utils import has_feature
from transactions.fx import get_usd_to_clp
from transactions.models import Transaction

# ✅ NUEVO: Budgets (usa tu modelo real)
try:
    from budgets.models import (BudgetCategory, MonthlyBudget,  # type: ignore
                                month_start)
except Exception:
    BudgetCategory = None
    MonthlyBudget = None

    def month_start(d):  # fallback
        if not d:
            d = timezone.localdate()
        return d.replace(day=1)


from .models import TelegramConversation, TelegramLink

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# i18n messages (Telegram texts)
# ------------------------------------------------------------
def _lang_for_profile(prof: UserProfile) -> str:
    lang = getattr(prof, "language", None) or "es"
    return lang if lang in ("es", "en") else "es"


_MSG = {
    "es": {
        "not_linked": "Aún no estás vinculado. En la web: Vincular Telegram.",

        # ✅ Mensajes corregidos para que el usuario entienda que debe venir desde el link de la web
        "link_need_code": (
            "⚠️ Para vincular tu cuenta debes usar el botón **Vincular Telegram** desde la web.\n\n"
            "Entra a la web → Vincular Telegram → Abrir Telegram.\n"
            "Luego presiona START y quedará vinculado automáticamente ✅"
        ),
        "link_bad_code": (
            "❌ Código inválido o expirado.\n"
            "Vuelve a la web → Vincular Telegram → Abrir Telegram para generar uno nuevo."
        ),

        "link_ok": (
            "✅ Listo, Telegram vinculado.\n\n"
            "Opciones rápidas:\n"
            "1) 🧾 Registrar gasto o ingreso (en un mensaje o paso a paso)\n"
            "2) 💳 Registrar pago de tarjeta\n"
            "3) 🤝 Registrar préstamo\n"
            "4) 🔎 Consultar movimientos o resumen"
        ),
        "upgrade": "⭐ Esta función es de un plan superior. Revisa los planes en la web.",
        "help": (
            "Puedo ayudarte con estas opciones:\n\n"
            "1) 🧾 Registrar un gasto o ingreso\n"
            "   - En un mensaje:\n"
            "     Gasto 3.290 Uber\n"
            "     Ingreso 500.000 Sueldo\n"
            "     Gasto 12 USD Burger\n"
            "   - Paso a paso:\n"
            "     Escribe: Gasto\n"
            "     o: Ingreso\n"
            "     y te voy preguntando monto, moneda, descripción y tarjeta (si aplica).\n\n"
            "2) 💳 Pago de tarjeta\n"
            "   - En un mensaje:\n"
            "     Pago tarjeta 120.000 Itaú\n"
            "   - Paso a paso:\n"
            "     Escribe: Pago tarjeta\n"
            "     y te pregunto el monto y qué tarjeta estás pagando.\n\n"
            "3) 🤝 Préstamos\n"
            "   Préstamo 45000 a Rosa (si faltan datos, te pregunto cuotas y primera fecha).\n\n"
            "4) 🔎 Consultas\n"
            "   Movimientos hoy\n"
            "   Movimientos 2025-12-18\n"
            "   Resumen 2025-12\n"
            "   Movimientos 2025-12-10 a 2025-12-15 (Plus/Pro)\n\n"
            "5) 🗑️ Eliminar\n"
            "   Eliminar 123\n"
            "   Eliminar último\n\n"
            "Tip tarjetas: si quieres asociar un gasto a una tarjeta, agrega el banco al final.\n"
            "Ejemplo: Gasto 12000 Uber Itaú\n"
            "Si hay más de una, te pregunto cuál.\n\n"
            "En cualquier paso puedes cancelar con: C"
        ),
        "tx_parse_fail": (
            "No pude interpretar tu mensaje.\n\n"
            "Opciones:\n"
            "1) 🧾 Registrar gasto o ingreso\n"
            "   - En un mensaje: Gasto 3290 Uber  |  Ingreso 500000 Sueldo\n"
            "   - Paso a paso: escribe Gasto o Ingreso\n\n"
            "2) 💳 Pago de tarjeta\n"
            "   - En un mensaje: Pago tarjeta 120000 Itaú\n"
            "   - Paso a paso: escribe Pago tarjeta\n\n"
            "3) 🤝 Préstamo: Préstamo 45000 a Rosa\n"
            "4) 🔎 Consultas: Movimientos hoy  |  Resumen 2025-12\n\n"
            "Tip: para USD agrega USD o $.\n"
            "Puedes cancelar en cualquier momento con: C"
        ),
        "tx_saved": "✅ Registrado: {label} {amount} {cur}{approx} · {desc}\nID: {id}",
        "tx_dupe": "ℹ️ Ese mensaje ya estaba registrado (no lo dupliqué).",
        "delete_need_id": "Indica el ID. Ejemplo: Eliminar 123 o Eliminar último.",
        "delete_not_found": "No encontré ese movimiento (o no es tuyo).",
        "delete_ok": "🗑️ Eliminado: {label} {amount} {cur} · {desc}\nID: {id}",
        "movements_none": "No hay movimientos para esa fecha.",
        "movements_range_none": "No hay movimientos en ese rango.",
        "movements_header": "📅 Movimientos {day}:",
        "movements_range_header": "📅 Movimientos {a} a {b}:",
        "summary_header": "📊 Resumen {ym}:",
        "loans_none": "No tienes préstamos activos.",
        "loans_header": "🤝 Préstamos activos:",
        "loan_created": "✅ Préstamo creado: {amount} {cur}{approx} a {person} · {n} cuotas · primer vencimiento {due}",
        "loan_ask_installments": "Perfecto. ¿En cuántas cuotas? (ejemplo: 3)",
        "loan_ask_first_due": "¿Cuál es la primera fecha de pago? Formato YYYY-MM-DD. Ejemplo: 2026-01-15",
        "loan_bad_date": "Fecha inválida. Usa formato YYYY-MM-DD. Ejemplo: 2026-01-15",
        "loan_bad_installments": "No entendí las cuotas. Envíame solo un número (ejemplo: 3).",
        "card_ask": (
            "💳 ¿Con qué tarjeta fue este gasto?\n"
            "Responde con 1, 2, 3...\n\n"
            "{cards}\n\n"
            "0) Sin tarjeta\n"
            "C) Cancelar"
        ),
        "card_linked": "✅ Listo. Asocié el movimiento a la tarjeta: {card}.",
        "card_skip": "👌 Ok, dejo el movimiento sin tarjeta.",
        "card_not_found": "No logré interpretarlo. Responde con 1, 2, 3... o 0 para sin tarjeta, o C para cancelar.",
        "card_no_cards": "No tienes tarjetas creadas en la web. Crea una en Cards y luego intenta de nuevo.",
        "card_cancel": "✅ Ok, cancelé y no hice cambios.",
        "card_pay_ask": (
            "💳 ¿Qué tarjeta estás pagando?\n"
            "Responde con 1, 2, 3...\n\n"
            "{cards}\n\n"
            "C) Cancelar"
        ),
        "card_pay_not_found": "No logré interpretarlo. Responde con 1, 2, 3... o C para cancelar.",
        "card_payment_applied": "✅ Listo. Registré el pago y aboné el saldo de {card}. ID: {id}",
        "card_payment_missing_balance": "✅ Listo. Registré el pago en {card}. ID: {id}",
        "tx_confirm_title": "✅ Antes de guardar, revisa si está correcto:",
        "tx_confirm_actions_expense": (
            "Responde con una opción:\n"
            "1) Guardar\n"
            "2) Editar monto\n"
            "3) Editar moneda\n"
            "4) Editar descripción\n"
            "5) Editar tarjeta\n"
            "6) Cambiar tipo (gasto/ingreso)\n"
            "0) Cancelar"
        ),
        "tx_confirm_actions_income": (
            "Responde con una opción:\n"
            "1) Guardar\n"
            "2) Editar monto\n"
            "3) Editar moneda\n"
            "4) Editar descripción\n"
            "6) Cambiar tipo (gasto/ingreso)\n"
            "0) Cancelar"
        ),
        "tx_confirm_actions_payment": (
            "Responde con una opción:\n"
            "1) Guardar\n"
            "2) Editar monto\n"
            "3) Editar moneda\n"
            "5) Editar tarjeta\n"
            "0) Cancelar"
        ),
        "tx_cancel_ok": "🚫 Ok, cancelé. No guardé nada.",
        "tx_edit_amount_ask": "💰 Dime el monto. Ejemplos: 3290  |  3.290  |  12 USD\nC) Cancelar",
        "tx_edit_currency_ask": "💱 ¿Qué moneda es? Responde CLP o USD.\nC) Cancelar",
        "tx_edit_desc_ask": "📝 Dime la descripción. Ejemplo: Uber, supermercado, arriendo...\nC) Cancelar",
        "tx_edit_kind_ask": "🔄 ¿Qué es? Responde: Gasto o Ingreso.\nC) Cancelar",
        "tx_need_card_for_payment": "Para registrar un pago de tarjeta necesito que elijas una tarjeta. Si no tienes, crea una en la web (Cards).",

        # ✅ NUEVO: Categorías / Presupuestos
        "cat_unknown": (
            "🔎 No encontré una categoría para: *{kw}*\n\n"
            "¿Qué quieres hacer?\n"
            "1) Asociar a una categoría existente\n"
            "2) Crear una nueva categoría\n"
            "0) Dejar sin categoría\n"
            "C) Cancelar"
        ),
        "cat_pick_existing": (
            "📌 Elige una categoría para asociar *{kw}*.\n"
            "Responde con 1, 2, 3...\n\n"
            "{cats}\n\n"
            "C) Cancelar"
        ),
        "cat_new_ask_name": (
            "🆕 Perfecto. ¿Cómo se llama la nueva categoría?\n"
            "Ej: Transporte, Comida, Supermercado...\n"
            "C) Cancelar"
        ),
        "cat_new_pick_existing_budget": (
            "📆 ¿Quieres crear el presupuesto mensual de esta categoría?\n"
            "Elige una opción:\n\n"
            "{buds}\n\n"
            "N) Definir un monto nuevo\n"
            "0) No crear presupuesto ahora\n"
            "C) Cancelar"
        ),
        "cat_new_ask_amount": (
            "💰 ¿Cuál es el presupuesto mensual (CLP) para esta categoría?\n"
            "Ej: 150000\n"
            "C) Cancelar"
        ),
        "cat_linked_ok": "✅ Listo. Asocié *{kw}* a la categoría: {cat}.",
        "cat_created_ok": "✅ Categoría creada: {cat}.",
        "cat_skipped": "👌 Ok, dejo el gasto sin categoría.",
        "cat_invalid": "No entendí. Responde con 1, 2, 3... o C para cancelar.",
        "cat_no_categories": "No tienes categorías creadas aún. Elige 2 para crear una nueva.",
        "cat_no_budgets": "No encontré presupuestos mensuales creados para este mes. Puedes definir un monto nuevo (N) o 0 para saltar.",

        # ---- OCR ----
        "ocr_result_header": "🧾 Texto detectado en la foto:",
        "ocr_no_text": (
            "No pude detectar texto en la foto.\n\n"
            "Tips rápidos:\n"
            "• Acércate más a la boleta\n"
            "• Buena luz (sin sombras)\n"
            "• Que se vea nítida (sin movimiento)\n"
            "• Evita reflejos/brillos\n"
        ),
        "ocr_failed": (
            "No pude leer la foto por ahora.\n"
            "En desarrollo local revisa que Tesseract esté instalado y con idioma español (spa).\n"
        ),
    },
    "en": {
        "not_linked": "You are not linked yet. On the web: Link Telegram.",

        # ✅ Updated messages
        "link_need_code": (
            "⚠️ To link your account, use the **Link Telegram** button on the web.\n\n"
            "Go to the web → Link Telegram → Open Telegram.\n"
            "Then press START and it will link automatically ✅"
        ),
        "link_bad_code": (
            "❌ Invalid or expired code.\n"
            "Go back to the web → Link Telegram → Open Telegram to generate a new one."
        ),

        "link_ok": (
            "✅ Linked.\n\n"
            "Quick options:\n"
            "1) 🧾 Record expense or income (one message or step by step)\n"
            "2) 💳 Record card payment\n"
            "3) 🤝 Record a loan\n"
            "4) 🔎 Query movements or summary"
        ),
        "upgrade": "⭐ This is a higher plan feature. Please upgrade on the web.",
        "help": (
            "I can help with these options:\n\n"
            "1) 🧾 Record an expense or income\n"
            "   - In one message:\n"
            "     Expense 3,290 Uber\n"
            "     Income 500,000 Salary\n"
            "     Expense 12 USD Burger\n"
            "   - Step by step:\n"
            "     Send: Expense\n"
            "     or: Income\n"
            "     and I’ll ask amount, currency, description and card (if applicable).\n\n"
            "2) 💳 Card payment\n"
            "   - In one message:\n"
            "     Card payment 120000 Itau\n"
            "   - Step by step:\n"
            "     Send: Card payment\n"
            "     and I’ll ask amount and which card you’re paying.\n\n"
            "3) 🤝 Loans\n"
            "   Loan 45000 to Rosa (if missing info, I’ll ask installments and first due date).\n\n"
            "4) 🔎 Queries\n"
            "   Movements today\n"
            "   Movements 2025-12-18\n"
            "   Summary 2025-12\n"
            "   Movements 2025-12-10 to 2025-12-15 (Plus/Pro)\n\n"
            "5) 🗑️ Delete\n"
            "   Delete 123\n"
            "   Delete last\n\n"
            "You can cancel anytime with: C"
        ),
        "tx_parse_fail": (
            "I couldn’t understand your message.\n\n"
            "Options:\n"
            "1) 🧾 Record expense or income\n"
            "2) 💳 Card payment\n"
            "3) 🤝 Loan\n"
            "4) 🔎 Queries\n\n"
            "You can cancel anytime with: C"
        ),
        "tx_saved": "✅ Saved: {label} {amount} {cur}{approx} · {desc}\nID: {id}",
        "tx_dupe": "ℹ️ That message was already recorded (no duplicate).",
        "delete_need_id": "Provide an ID. Example: Delete 123 or Delete last.",
        "delete_not_found": "I couldn’t find that transaction (or it’s not yours).",
        "delete_ok": "🗑️ Deleted: {label} {amount} {cur} · {desc}\nID: {id}",
        "movements_none": "No movements for that date.",
        "movements_range_none": "No movements in that range.",
        "movements_header": "📅 Movements {day}:",
        "movements_range_header": "📅 Movements {a} to {b}:",
        "summary_header": "📊 Summary {ym}:",
        "loans_none": "No active loans.",
        "loans_header": "🤝 Active loans:",
        "loan_created": "✅ Loan created: {amount} {cur}{approx} to {person} · {n} installments · first due {due}",
        "loan_ask_installments": "Great. How many installments? (example: 3)",
        "loan_ask_first_due": "What is the first due date? Format YYYY-MM-DD. Example: 2026-01-15",
        "loan_bad_date": "Invalid date. Use YYYY-MM-DD. Example: 2026-01-15",
        "loan_bad_installments": "I didn’t get the installments. Send just a number (example: 3).",
        "card_ask": (
            "💳 Which card was this expense on?\n"
            "Reply with 1, 2, 3...\n\n"
            "{cards}\n\n"
            "0) No card\n"
            "C) Cancel"
        ),
        "card_linked": "✅ Done. I linked the transaction to card: {card}.",
        "card_skip": "👌 Ok, I’ll keep it with no card.",
        "card_not_found": "I didn’t get that. Reply 1, 2, 3... or 0 for no card, or C to cancel.",
        "card_no_cards": "You don’t have cards created on the web. Create one in Cards and try again.",
        "card_cancel": "✅ Ok, canceled. No changes made.",
        "card_pay_ask": (
            "💳 Which card are you paying?\n"
            "Reply with 1, 2, 3...\n\n"
            "{cards}\n\n"
            "C) Cancel"
        ),
        "card_pay_not_found": "I didn’t get that. Reply 1, 2, 3... or C to cancel.",
        "card_payment_applied": "✅ Done. I recorded the payment and applied it to {card}. ID: {id}",
        "card_payment_missing_balance": "✅ Done. I recorded the payment to {card}. ID: {id}",
        "tx_confirm_title": "✅ Before saving, please confirm this is correct:",
        "tx_confirm_actions_expense": (
            "Reply with an option:\n"
            "1) Save\n"
            "2) Edit amount\n"
            "3) Edit currency\n"
            "4) Edit description\n"
            "5) Edit card\n"
            "6) Change type (expense/income)\n"
            "0) Cancel"
        ),
        "tx_confirm_actions_income": (
            "Reply with an option:\n"
            "1) Save\n"
            "2) Edit amount\n"
            "3) Edit currency\n"
            "4) Edit description\n"
            "6) Change type (expense/income)\n"
            "0) Cancel"
        ),
        "tx_confirm_actions_payment": (
            "Reply with an option:\n"
            "1) Save\n"
            "2) Edit amount\n"
            "3) Edit currency\n"
            "5) Edit card\n"
            "0) Cancel"
        ),
        "tx_cancel_ok": "🚫 Ok, canceled. Nothing was saved.",
        "tx_edit_amount_ask": "💰 Tell me the amount. Examples: 3290  |  3,290  |  12 USD\nC) Cancel",
        "tx_edit_currency_ask": "💱 Which currency? Reply CLP or USD.\nC) Cancel",
        "tx_edit_desc_ask": "📝 Tell me the description.\nC) Cancel",
        "tx_edit_kind_ask": "🔄 Which type? Reply: Expense or Income.\nC) Cancel",
        "tx_need_card_for_payment": "To record a card payment you must choose a card. If you don’t have one, create it on the web (Cards).",

        # ✅ NEW: Categories / Budgets
        "cat_unknown": (
            "🔎 I couldn't find a category for: *{kw}*\n\n"
            "What do you want to do?\n"
            "1) Link to an existing category\n"
            "2) Create a new category\n"
            "0) Leave uncategorized\n"
            "C) Cancel"
        ),
        "cat_pick_existing": (
            "📌 Pick a category to link *{kw}*.\n"
            "Reply with 1, 2, 3...\n\n"
            "{cats}\n\n"
            "C) Cancel"
        ),
        "cat_new_ask_name": "🆕 What is the new category name?\nC) Cancel",
        "cat_new_pick_existing_budget": (
            "📆 Do you want to create the monthly budget for this category?\n\n"
            "{buds}\n\n"
            "N) Set a new amount\n"
            "0) Don't create now\n"
            "C) Cancel"
        ),
        "cat_new_ask_amount": "💰 Monthly budget amount (CLP)? Example: 150000\nC) Cancel",
        "cat_linked_ok": "✅ Done. Linked *{kw}* to category: {cat}.",
        "cat_created_ok": "✅ Category created: {cat}.",
        "cat_skipped": "👌 Ok, leaving it uncategorized.",
        "cat_invalid": "I didn’t get that. Reply with a number or C to cancel.",
        "cat_no_categories": "No categories yet. Choose option 2 to create one.",
        "cat_no_budgets": "No monthly budgets found for this month. You can set a new amount (N) or 0 to skip.",

        # ---- OCR ----
        "ocr_result_header": "🧾 Text detected in the photo:",
        "ocr_no_text": "I couldn’t detect text in the photo.",
        "ocr_failed": "I couldn’t read that photo right now.",
    },
}


# ------------------------------------------------------------
# Telegram helpers
# ------------------------------------------------------------
def _bot_token() -> str:
    tok = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or getattr(settings, "TELEGRAM_TOKEN", "")
    if not tok:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en settings/.env")
    return tok


def tg_send_message(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{_bot_token()}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=12).raise_for_status()
    except Exception as e:
        logger.exception("Telegram sendMessage failed: %s", e)


def tg_send_long_message(chat_id: int, text: str, chunk_size: int = 3500) -> None:
    """
    Telegram suele limitar a ~4096 chars por mensaje.
    Cortamos seguro para evitar error.
    """
    if not text:
        return
    s = str(text)
    while s:
        part = s[:chunk_size]
        s = s[chunk_size:]
        tg_send_message(chat_id, part)


def _tg_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{_bot_token()}/{method}"


def tg_get_file_bytes(file_id: str) -> Optional[bytes]:
    """
    Descarga bytes de un file_id de Telegram usando getFile.
    """
    if not file_id:
        return None

    try:
        r = requests.get(_tg_api_url("getFile"), params={"file_id": file_id}, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
        if not data.get("ok"):
            return None

        file_path = (data.get("result") or {}).get("file_path")
        if not file_path:
            return None

        file_url = f"https://api.telegram.org/file/bot{_bot_token()}/{file_path}"
        r2 = requests.get(file_url, timeout=30)
        r2.raise_for_status()

        # Protección básica de tamaño (evitar que te suban 200MB)
        max_bytes = int(getattr(settings, "TELEGRAM_MAX_OCR_BYTES", 12 * 1024 * 1024))  # 12MB default
        if len(r2.content) > max_bytes:
            return None

        return r2.content
    except Exception:
        logger.exception("tg_get_file_bytes failed (file_id=%s)", file_id)
        return None


# ------------------------------------------------------------
# OCR helpers
# ------------------------------------------------------------
_OCR_HINT_WORDS = (
    "ocr",
    "leer",
    "lee",
    "texto",
    "text",
    "scan",
    "boleta",
    "factura",
    "receipt",
    "invoice",
)


def _should_ocr_for_message(text: str, has_media: bool) -> bool:
    """
    Regla:
    - Si llega media (foto/documento) SIN caption/texto => hacemos OCR automático.
    - Si llega con caption y contiene hint => hacemos OCR.
    """
    if not has_media:
        return False
    t = (text or "").strip().lower()
    if not t:
        return True
    return any(w in t for w in _OCR_HINT_WORDS)


def _is_pdf_bytes(b: bytes) -> bool:
    return bool(b) and b[:4] == b"%PDF"


def _preprocess_image_for_ocr(file_bytes: bytes) -> bytes:
    """
    Preproceso para boletas: grayscale + resize + contraste + sharpen.
    Devuelve PNG para OCR.
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter  # type: ignore
    except Exception:
        return file_bytes  # sin Pillow, no preprocesamos

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = img.convert("L")  # grayscale

        w, h = img.size
        scale = 2 if max(w, h) < 1600 else 1
        if scale > 1:
            img = img.resize((w * scale, h * scale))

        img = ImageEnhance.Contrast(img).enhance(1.8)
        img = img.filter(ImageFilter.SHARPEN)

        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        logger.exception("OCR preprocess failed")
        return file_bytes


def _clean_ocr_text(text: str) -> str:
    t = (text or "").replace("\r", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = "\n".join([ln.strip() for ln in t.split("\n")]).strip()
    return t


def _ocr_via_ocrspace(file_bytes: bytes, lang: str) -> Optional[str]:
    """
    OCR vía ocr.space (opcional). Requiere OCR_SPACE_API_KEY.
    Si no hay key, retorna None.
    """
    api_key = getattr(settings, "OCR_SPACE_API_KEY", "") or ""
    if not api_key:
        return None

    ocr_lang = "spa" if lang == "es" else "eng"
    url = "https://api.ocr.space/parse/image"

    try:
        if _is_pdf_bytes(file_bytes):
            upload_bytes = file_bytes
            filename = "upload.pdf"
            mimetype = "application/pdf"
        else:
            upload_bytes = _preprocess_image_for_ocr(file_bytes)
            filename = "upload.png"
            mimetype = "image/png"

        files = {"file": (filename, io.BytesIO(upload_bytes), mimetype)}
        data = {
            "apikey": api_key,
            "language": ocr_lang,
            "isOverlayRequired": "false",
            "scale": "true",
            "detectOrientation": "true",
            "OCREngine": "2",
        }

        r = requests.post(url, files=files, data=data, timeout=45)
        r.raise_for_status()
        js = r.json() or {}
        if js.get("IsErroredOnProcessing"):
            return None
        parsed = (js.get("ParsedResults") or [])
        if not parsed:
            return None
        text = (parsed[0] or {}).get("ParsedText") or ""
        text = text.strip()
        return text or None
    except Exception:
        logger.exception("OCR via ocr.space failed")
        return None


def _guess_tessdata_dir() -> Optional[str]:
    candidates = [
        os.environ.get("TESSDATA_PREFIX", ""),
        "/opt/homebrew/share/tessdata",
        "/usr/local/share/tessdata",
    ]
    for p in candidates:
        if p and os.path.isdir(p):
            return p
    return None


def _tess_has_lang(tessdata_dir: str, lang: str) -> bool:
    try:
        return os.path.isfile(os.path.join(tessdata_dir, f"{lang}.traineddata"))
    except Exception:
        return False


def _ocr_via_tesseract(file_bytes: bytes, lang: str) -> Optional[str]:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return None

    try:
        cmd = shutil.which("tesseract")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
    except Exception:
        pass

    try:
        tessdata = _guess_tessdata_dir()
        if tessdata and not os.environ.get("TESSDATA_PREFIX"):
            os.environ["TESSDATA_PREFIX"] = tessdata
    except Exception:
        pass

    if _is_pdf_bytes(file_bytes):
        return None

    try:
        pre = _preprocess_image_for_ocr(file_bytes)
        img = Image.open(io.BytesIO(pre))

        desired = "spa" if lang == "es" else "eng"
        tessdata_dir = os.environ.get("TESSDATA_PREFIX", "") or ""
        chosen_lang = desired

        if desired == "spa":
            if tessdata_dir and not _tess_has_lang(tessdata_dir, "spa"):
                chosen_lang = "eng"
            else:
                chosen_lang = "spa+eng"

        text = pytesseract.image_to_string(img, lang=chosen_lang) or ""
        text = (text or "").strip()
        return text or None
    except Exception:
        logger.exception("OCR via tesseract failed")
        return None


def ocr_bytes_to_text(file_bytes: bytes, lang: str) -> Optional[str]:
    if not file_bytes:
        return None

    text = _ocr_via_ocrspace(file_bytes, lang)
    if text:
        return _clean_ocr_text(text)

    text = _ocr_via_tesseract(file_bytes, lang)
    if text:
        return _clean_ocr_text(text)

    return None


def _extract_best_file_id_from_msg(msg: dict) -> Optional[str]:
    if not msg:
        return None

    if msg.get("photo"):
        photos = msg.get("photo") or []
        if isinstance(photos, list) and photos:
            best = photos[-1]
            return best.get("file_id")

    doc = msg.get("document")
    if isinstance(doc, dict) and doc.get("file_id"):
        return doc.get("file_id")

    return None


# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------
def _fmt_clp(x: Decimal) -> str:
    x = (x or Decimal("0")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(x):,}".replace(",", ".")


def _fmt_usd(x: Decimal) -> str:
    x = (x or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _money(amount: Decimal, cur: str, lang: str) -> str:
    if cur == "USD":
        return _fmt_usd(amount) if lang == "es" else f"{Decimal(amount):,.2f}"
    return _fmt_clp(amount) if lang == "es" else f"{int(Decimal(amount)):,}"


def _label(kind: str, lang: str) -> str:
    if lang == "en":
        return "Expense" if kind == "expense" else "Income"
    return "Gasto" if kind == "expense" else "Ingreso"


# ------------------------------------------------------------
# Parsing TX
# ------------------------------------------------------------
@dataclass(frozen=True)
class ParsedTx:
    kind: str
    amount_original: Decimal
    currency_original: str
    description: str
    raw_text: str


_KIND_EXP = ("gasto", "expense", "egreso", "out")
_KIND_INC = ("ingreso", "income", "in")

_CURRENCY_USD = ("usd", "dolar", "dólar", "dolares", "dólares", "$us", "us$", "uds", "ud", "usds")
_CURRENCY_CLP = ("clp", "peso", "pesos", "ch$", "$clp")


def _to_decimal_num(s: str, currency: str) -> Decimal:
    raw = (s or "").strip().replace(" ", "")
    if not raw:
        return Decimal("0")

    raw = re.sub(r"[^0-9\.,\-]", "", raw)

    if raw.count(".") and raw.count(","):
        if raw.rfind(".") > raw.rfind(","):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(","):
        if currency == "USD" and re.match(r"^-?\d+,\d{1,2}$", raw):
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif raw.count("."):
        if currency == "CLP":
            raw = raw.replace(".", "")
        else:
            if not re.match(r"^-?\d+\.\d{1,2}$", raw):
                raw = raw.replace(".", "")

    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _detect_currency_from_text(low: str) -> str:
    low = (low or "").lower()
    if any(c in low for c in _CURRENCY_CLP) or re.search(r"\bclp\b", low):
        return "CLP"
    if any(c in low for c in _CURRENCY_USD) or re.search(r"\busd\b", low):
        return "USD"
    if re.search(r"(\d[\d\.,]*)\s*\$", low) and ("ch$" not in low) and ("clp" not in low):
        return "USD"
    return "CLP"


def parse_text_to_tx(text: str) -> Optional[ParsedTx]:
    if not text:
        return None

    original = text.strip()
    low = original.lower().strip()

    kind = None
    for k in _KIND_EXP:
        if low.startswith(k + " "):
            kind = "expense"
            low = low[len(k):].strip()
            break
    if kind is None:
        for k in _KIND_INC:
            if low.startswith(k + " "):
                kind = "income"
                low = low[len(k):].strip()
                break
    if kind is None:
        return None

    currency = _detect_currency_from_text(low)

    m = re.search(r"(-?\d[\d\.,]*)", low)
    if not m:
        return None

    amount = _to_decimal_num(m.group(1), currency)
    if amount == 0:
        return None

    desc = (low[:m.start()] + " " + low[m.end():]).strip()
    desc = re.sub(r"\b(usd|clp|dolar|dólar|dolares|dólares|peso|pesos|uds|ud|usds)\b", "", desc)
    desc = desc.replace("$", " ")
    desc = re.sub(r"\s+", " ", desc).strip()
    if not desc:
        desc = "—"

    return ParsedTx(kind=kind, amount_original=amount, currency_original=currency, description=desc, raw_text=original)


# ------------------------------------------------------------
# Card payment parsing (pago de tarjeta) -> Draft TX (expense)
# ------------------------------------------------------------
_CARD_PAY_PREFIXES = (
    "pago tarjeta",
    "pago de tarjeta",
    "pagar tarjeta",
    "pago tc",
    "pago de tc",
    "pago t/c",
    "card payment",
    "pay card",
    "payment card",
)


def parse_text_to_card_payment(text: str) -> Optional[ParsedTx]:
    if not text:
        return None

    original = text.strip()
    low = original.lower().strip()

    matched = None
    for p in _CARD_PAY_PREFIXES:
        if low.startswith(p):
            matched = p
            break
    if not matched:
        return None

    rest = low[len(matched):].strip()
    if not rest:
        return None

    currency = _detect_currency_from_text(rest)
    m = re.search(r"(-?\d[\d\.,]*)", rest)
    if not m:
        return None

    amount = _to_decimal_num(m.group(1), currency)
    if amount == 0:
        return None

    desc = "Pago tarjeta" if _norm(_lang_hint_from_text(original)) != "en" else "Card payment"
    return ParsedTx(kind="expense", amount_original=amount, currency_original=currency, description=desc, raw_text=original)


def _lang_hint_from_text(text: str) -> str:
    low = (text or "").lower()
    if any(w in low for w in ("expense", "income", "loan", "card payment", "pay card", "payment")):
        return "en"
    return "es"


def create_tx_from_telegram(
    user,
    telegram_message_id: int,
    occurred_at,
    parsed: ParsedTx,
    card: Optional[Card] = None,
) -> Tuple[Transaction, bool]:
    occurred_at = occurred_at or timezone.now()

    if parsed.currency_original == "USD":
        fx = get_usd_to_clp()
        fx_rate = (fx.rate or Decimal("1")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        fx_source = fx.source or "fx"
        fx_timestamp = timezone.now()
        amount_clp = (parsed.amount_original * fx_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        fx_rate = Decimal("1")
        fx_source = "base"
        fx_timestamp = timezone.now()
        amount_clp = Decimal(parsed.amount_original).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    defaults = dict(
        kind=parsed.kind,
        description=parsed.description,
        occurred_at=occurred_at,
        amount_original=parsed.amount_original,
        currency_original=parsed.currency_original,
        amount_clp=amount_clp,
        fx_rate=fx_rate,
        fx_source=fx_source,
        fx_timestamp=fx_timestamp,
        card=card,
    )

    obj, created = Transaction.objects.get_or_create(
        user=user,
        telegram_message_id=telegram_message_id,
        defaults=defaults,
    )
    return obj, created


# ------------------------------------------------------------
# Card resolution
# ------------------------------------------------------------
def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s


def _card_label(c: Card) -> str:
    parts = []
    if getattr(c, "bank", ""):
        parts.append(str(c.bank))
    if getattr(c, "brand", ""):
        parts.append(str(c.brand))
    last4 = getattr(c, "last4", "") or ""
    if last4:
        parts.append(f"****{last4}")
    name = getattr(c, "name", "") or ""
    if name:
        return f"{name} · " + " · ".join(parts) if parts else name
    return " · ".join(parts) if parts else f"Card #{c.id}"


def _extract_last4_hint(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{4})\b", text or "")
    return m.group(1) if m else None


def _text_mentions_card(text: str) -> bool:
    low = _norm(text)
    return ("tarjeta" in low) or ("card" in low) or ("credito" in low) or ("credit" in low)


def _resolve_card_from_text(user, text: str) -> Tuple[Optional[Card], List[Card]]:
    cards = list(Card.objects.filter(user=user, is_active=True).order_by("name", "id"))
    if not cards:
        return (None, [])

    tnorm = _norm(text)

    last4 = _extract_last4_hint(tnorm)
    if last4:
        cands = [c for c in cards if str(getattr(c, "last4", "") or "") == last4]
        if len(cands) == 1:
            return (cands[0], cands)
        if len(cands) > 1:
            return (None, cands)

    words = [w for w in re.split(r"[^a-z0-9áéíóúñü]+", tnorm) if w]
    stop = set(["gasto", "expense", "ingreso", "income", "tarjeta", "card", "credito", "credit", "clp", "usd", "pago", "payment"])
    words = [w for w in words if len(w) >= 3 and w not in stop]

    if not words:
        return (None, [])

    scored: List[Tuple[int, Card]] = []
    for c in cards:
        blob = _norm(f"{getattr(c, 'name', '')} {getattr(c, 'bank', '')} {getattr(c, 'brand', '')} {getattr(c, 'last4', '')}")
        score = 0
        for w in words:
            if w and w in blob:
                score += 1
        if score > 0:
            scored.append((score, c))

    if not scored:
        return (None, [])

    scored.sort(key=lambda x: (-x[0], x[1].id))
    best_score = scored[0][0]
    best = [c for s, c in scored if s == best_score]

    if len(best) == 1:
        return (best[0], best)

    return (None, best)


def _render_cards_for_prompt(cards: List[Card]) -> str:
    lines = []
    for i, c in enumerate(cards[:8], start=1):
        lines.append(f"{i}) {_card_label(c)}")
    if len(cards) > 8:
        lines.append(f"... (+{len(cards) - 8} más)")
    return "\n".join(lines) if lines else "(sin tarjetas)"


def _parse_card_choice_number(text: str, max_n: int) -> Optional[int]:
    t = (text or "").strip().lower()
    if not t:
        return None

    if t in ("0", "sin tarjeta", "sintarjeta", "no card", "none", "ninguna", "sin", "no"):
        return 0

    if t.isdigit():
        n = int(t)
        if 0 <= n <= max_n:
            return n

    return None


def _is_skip_card_reply(text: str) -> bool:
    low = _norm(text)
    return low in ("sin tarjeta", "no card", "none", "ninguna", "sin", "no", "0")


def _is_cancel_card_reply(text: str) -> bool:
    low = _norm(text)
    return low in ("cancelar", "cancel", "c", "/cancel", "/cancelar")


def _apply_card_payment_to_balance(card: Card, amount_clp: Decimal) -> bool:
    try:
        amt = Decimal(amount_clp or Decimal("0")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except Exception:
        return False
    if amt <= 0:
        return False

    candidates = [
        "balance_clp",
        "current_balance_clp",
        "outstanding_clp",
        "debt_clp",
        "saldo_clp",
        "balance",
        "current_balance",
        "outstanding",
        "debt",
        "saldo",
        "saldo_utilizado",
        "used_amount",
        "used",
        "utilizado",
    ]

    existing = {f.name for f in getattr(card._meta, "concrete_fields", [])}
    field = next((fn for fn in candidates if fn in existing), None)
    if not field:
        return False

    cur = getattr(card, field, None)
    try:
        cur_dec = Decimal(str(cur)) if cur is not None else Decimal("0")
    except Exception:
        cur_dec = Decimal("0")

    new_val = (cur_dec - amt).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if new_val < 0:
        new_val = Decimal("0")

    try:
        setattr(card, field, new_val)
        card.save(update_fields=[field])
        return True
    except Exception:
        logger.exception("Failed to apply card payment to %s.%s", card.__class__.__name__, field)
        return False


# ------------------------------------------------------------
# ✅ NUEVO: Budget helpers (keyword -> category + MonthlyBudget)
# ------------------------------------------------------------
def _kw_from_description(desc: str) -> str:
    d = _norm(desc)
    stop = {"de", "del", "la", "el", "los", "las", "y", "para", "por", "en", "a", "un", "una"}
    words = [w for w in re.split(r"[^a-z0-9áéíóúñü]+", d) if w and w not in stop]
    return words[0] if words else (d[:24] or "—")


def _cat_label(cat) -> str:
    return getattr(cat, "name", None) or f"Cat #{getattr(cat, 'id', '')}"


def _parse_choice_1n_or_special(text: str, max_n: int) -> Optional[str]:
    """
    Returns:
      - "C" cancel
      - "0" skip
      - "N" new amount
      - "1".."max_n" numeric choice
      - None if invalid
    """
    t = (text or "").strip().lower()
    if t in ("c", "cancelar", "cancel", "/cancel", "/cancelar"):
        return "C"
    if t == "0":
        return "0"
    if t == "n":
        return "N"
    if t.isdigit():
        n = int(t)
        if 1 <= n <= max_n:
            return str(n)
    return None


def _parse_int_amount_clp(text: str) -> Optional[Decimal]:
    s = (text or "").strip().replace(" ", "")
    if not s:
        return None
    # "150.000" -> "150000"
    s = s.replace(".", "").replace(",", "")
    if not re.match(r"^-?\d+$", s):
        return None
    try:
        d = Decimal(s)
        if d <= 0:
            return None
        return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def _cat_keywords_norm_list(cat: BudgetCategory) -> List[str]:
    raw = (getattr(cat, "match_keywords", "") or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    out = []
    for p in parts:
        if not p:
            continue
        out.append(_norm(p))
    return [x for x in out if x]


def _find_category_for_keyword(user, kw: str) -> Optional[BudgetCategory]:
    if not BudgetCategory:
        return None
    kw_n = _norm(kw)
    if not kw_n:
        return None

    cats = BudgetCategory.objects.filter(user=user, is_active=True).order_by("name", "id")
    for c in cats:
        if kw_n in _cat_keywords_norm_list(c):
            return c
    return None


def _append_keyword_to_category(cat: BudgetCategory, kw: str) -> None:
    kw_n = _norm(kw)
    if not kw_n:
        return
    existing = _cat_keywords_norm_list(cat)
    if kw_n in existing:
        return

    raw = (cat.match_keywords or "").strip()
    if not raw:
        cat.match_keywords = kw_n
    else:
        cat.match_keywords = raw + ", " + kw_n
    cat.save(update_fields=["match_keywords"])


def _list_categories(user) -> List[BudgetCategory]:
    if not BudgetCategory:
        return []
    return list(BudgetCategory.objects.filter(user=user, is_active=True).order_by("name", "id"))


def _list_monthly_budgets_current_month(user) -> List[MonthlyBudget]:
    if not MonthlyBudget:
        return []
    m = month_start(timezone.localdate())
    return list(
        MonthlyBudget.objects.filter(user=user, month=m)
        .select_related("category")
        .order_by("category__name", "id")
    )


def _ensure_monthly_budget_for_category(user, category: BudgetCategory, amount_clp: Decimal) -> None:
    if not MonthlyBudget:
        return
    m = month_start(timezone.localdate())
    MonthlyBudget.objects.update_or_create(
        user=user,
        category=category,
        month=m,
        defaults={"amount_clp": amount_clp},
    )


def _render_categories_prompt(cats: List[BudgetCategory]) -> str:
    lines = []
    for i, c in enumerate(cats[:10], start=1):
        lines.append(f"{i}) {_cat_label(c)}")
    if len(cats) > 10:
        lines.append(f"... (+{len(cats) - 10} más)")
    return "\n".join(lines) if lines else "—"


def _render_monthly_budgets_prompt(buds: List[MonthlyBudget]) -> str:
    """
    Muestra presupuestos del mes actual. Elegir uno = copiar ese monto al nuevo MonthlyBudget.
    """
    lines = []
    for i, b in enumerate(buds[:10], start=1):
        cat_name = getattr(b.category, "name", "—")
        amt = getattr(b, "amount_clp", Decimal("0")) or Decimal("0")
        lines.append(f"{i}) {cat_name}: {_fmt_clp(Decimal(amt))} CLP")
    if len(buds) > 10:
        lines.append(f"... (+{len(buds) - 10} más)")
    return "\n".join(lines) if lines else "—"


# ------------------------------------------------------------
# Draft + Confirmation helpers
# ------------------------------------------------------------
def _draft_from_parsed(parsed: ParsedTx, telegram_message_id: int, occurred_at_iso: str) -> dict:
    return {
        "kind": parsed.kind,
        "amount_original": str(parsed.amount_original),
        "currency_original": parsed.currency_original,
        "description": parsed.description,
        "telegram_message_id": int(telegram_message_id),
        "occurred_at": occurred_at_iso,
        "card_id": None,
        "is_card_payment": False,
        # ✅ NUEVO: para budget-keywords MVP
        "budget_kw": _kw_from_description(parsed.description or ""),
        "budget_category_id": None,  # opcional (solo para UI/confirm, Transaction NO lo usa)
    }


def _draft_to_parsed(draft: dict) -> ParsedTx:
    return ParsedTx(
        kind=draft.get("kind") or "expense",
        amount_original=Decimal(str(draft.get("amount_original") or "0")),
        currency_original=draft.get("currency_original") or "CLP",
        description=draft.get("description") or "—",
        raw_text="draft",
    )


def _draft_summary_text(lang: str, draft: dict, user) -> str:
    kind = draft.get("kind") or "expense"
    label = _label(kind, lang)

    cur = draft.get("currency_original") or "CLP"
    amt = Decimal(str(draft.get("amount_original") or "0"))
    desc = draft.get("description") or "—"
    card_id = draft.get("card_id")
    is_payment = bool(draft.get("is_card_payment"))

    lines = [_MSG[lang]["tx_confirm_title"]]
    lines.append(f"Tipo: {('Pago de tarjeta' if (lang=='es' and is_payment) else ('Card payment' if is_payment else label))}")
    lines.append(f"Monto: {_money(amt, cur, lang)} {cur}")
    lines.append(f"Descripción: {desc}")

    # ✅ NUEVO: mostrar categoría estimada por keyword (si existe)
    if BudgetCategory and (draft.get("kind") == "expense") and not is_payment:
        cid = draft.get("budget_category_id")
        if cid:
            cat = BudgetCategory.objects.filter(user=user, id=int(cid)).first()
            if cat:
                lines.append(f"Categoría: {cat.name}")
        else:
            kw = draft.get("budget_kw") or _kw_from_description(desc)
            if kw:
                lines.append(f"Categoría: (sin asignar · keyword: {kw})")

    if kind == "expense" or is_payment:
        if card_id:
            c = Card.objects.filter(user=user, is_active=True, id=int(card_id)).first()
            if c:
                lines.append(f"Tarjeta: {_card_label(c)}")
            else:
                lines.append("Tarjeta: (no encontrada)")
        else:
            lines.append("Tarjeta: (sin tarjeta)")

    return "\n".join(lines)


def _set_state(conv: TelegramConversation, state: str, payload: dict) -> None:
    conv.state = state
    conv.payload = payload
    conv.save(update_fields=["state", "payload", "updated_at"])


def _parse_amount_and_currency_from_free_text(text: str) -> Tuple[Optional[Decimal], Optional[str]]:
    low = (text or "").strip().lower()
    cur = _detect_currency_from_text(low)
    m = re.search(r"(-?\d[\d\.,]*)", low)
    if not m:
        return (None, None)
    amt = _to_decimal_num(m.group(1), cur)
    if amt == 0:
        return (None, None)
    return (amt, cur)


def _parse_currency_only(text: str) -> Optional[str]:
    low = (text or "").strip().lower()
    if low in ("clp", "peso", "pesos"):
        return "CLP"
    if low in ("usd", "dolar", "dólar", "dolares", "dólares"):
        return "USD"
    if "clp" in low:
        return "CLP"
    if "usd" in low:
        return "USD"
    return None


def _parse_kind_only(text: str) -> Optional[str]:
    low = (text or "").strip().lower()
    if low in ("gasto", "expense", "egreso", "out"):
        return "expense"
    if low in ("ingreso", "income", "in"):
        return "income"
    return None


# ------------------------------------------------------------
# Parsing LOANS (igual que antes)
# ------------------------------------------------------------
@dataclass(frozen=True)
class ParsedLoan:
    direction: str
    person_name: str
    amount_original: Decimal
    currency_original: str
    installments: Optional[int]
    first_due: Optional[date]


def _parse_date_yyyy_mm_dd(s: str) -> Optional[date]:
    try:
        y, m, d = s.strip().split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_text_to_loan(text: str) -> Optional[ParsedLoan]:
    if not text:
        return None
    low = text.strip().lower()

    if not (("prestamo" in low) or ("préstamo" in low) or ("préstamos" in low) or ("presté" in low) or ("preste" in low) or ("me prest" in low)):
        return None

    direction = Loan.DIRECTION_LENT
    if "me prest" in low:
        direction = Loan.DIRECTION_BORROWED

    currency = _detect_currency_from_text(low)

    m_amount = re.search(r"(-?\d[\d\.,]*)", low)
    if not m_amount:
        return None
    amount = _to_decimal_num(m_amount.group(1), currency)
    if amount == 0:
        return None

    person = ""
    m_person = re.search(r"\b(a|para)\s+([a-záéíóúñü0-9 _\.\-]{2,}?)(\bcuotas\b|\ben\b|\bvence\b|\bprimer\b|\bpago\b|$)", low)
    if m_person:
        person = (m_person.group(2) or "").strip()

    person = re.sub(r"\s+", " ", person).strip().title()
    if not person:
        return None

    installments = None
    m_inst = re.search(r"\bcuotas?\s+(\d{1,3})\b", low) or re.search(r"\ben\s+(\d{1,3})\s+cuotas?\b", low)
    if m_inst:
        try:
            installments = int(m_inst.group(1))
        except Exception:
            installments = None

    first_due = None
    m_due = re.search(r"\b(vence|primer\s+pago|pago|primera\s+cuota)\s+(\d{4}-\d{2}-\d{2})\b", low)
    if m_due:
        first_due = _parse_date_yyyy_mm_dd(m_due.group(2))

    return ParsedLoan(
        direction=direction,
        person_name=person,
        amount_original=amount,
        currency_original=currency,
        installments=installments,
        first_due=first_due,
    )


def _loan_principal_clp(amount: Decimal, currency: str) -> Tuple[Decimal, Optional[Decimal], str]:
    if currency == "CLP":
        return (Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP), None, "base")

    fx = get_usd_to_clp()
    rate = (fx.rate or Decimal("1")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    clp = (Decimal(amount) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (clp, rate, fx.source or "fx")


# ------------------------------------------------------------
# Queries / Commands
# ------------------------------------------------------------
def _parse_movements_single_or_range(text: str) -> Tuple[Optional[date], Optional[date]]:
    low = text.strip().lower()
    if not low.startswith("mov"):
        return (None, None)

    if "hoy" in low or "today" in low:
        return (timezone.localdate(), None)
    if "ayer" in low or "yesterday" in low:
        return (timezone.localdate() - timedelta(days=1), None)

    dates = re.findall(r"\d{4}-\d{2}-\d{2}", low)
    if not dates:
        return (None, None)

    d1 = _parse_date_yyyy_mm_dd(dates[0])
    if len(dates) >= 2:
        d2 = _parse_date_yyyy_mm_dd(dates[1])
        return (d1, d2)
    return (d1, None)


def _parse_summary_query(text: str) -> Optional[Tuple[int, int]]:
    low = text.strip().lower()
    if not low.startswith("res"):
        return None
    m = re.search(r"(\d{4})-(\d{2})", low)
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2))
    if mo < 1 or mo > 12:
        return None
    return y, mo


def _parse_delete_cmd(text: str) -> Tuple[bool, Optional[int], bool]:
    low = text.strip().lower()
    if not (low.startswith("eliminar") or low.startswith("delete")):
        return (False, None, False)
    if "último" in low or "ultimo" in low or "last" in low:
        return (True, None, True)
    m = re.search(r"\b(\d{1,10})\b", low)
    if m:
        return (True, int(m.group(1)), False)
    return (True, None, False)


# ------------------------------------------------------------
# MAIN entrypoint (called from views.py)
# ------------------------------------------------------------
def handle_incoming_telegram_update(payload: dict) -> None:
    msg = payload.get("message") or payload.get("edited_message")
    if not msg:
        return

    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    tg_user_id = from_user.get("id")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    message_id = msg.get("message_id")

    if not (chat_id and tg_user_id and message_id):
        return

    # /start <code> => vincular
    if text.lower().startswith("/start"):
        parts = text.split()
        code = parts[1].strip() if len(parts) > 1 else ""

        if not code:
            tg_send_message(chat_id, _MSG["es"]["link_need_code"])
            return

        prof = UserProfile.objects.filter(telegram_link_code=code).select_related("user").first()
        if not prof:
            tg_send_message(chat_id, _MSG["es"]["link_bad_code"])
            return

        prof.telegram_user_id = tg_user_id
        prof.telegram_link_code = None
        prof.save(update_fields=["telegram_user_id", "telegram_link_code"])

        TelegramLink.objects.update_or_create(
            profile=prof,
            defaults={"telegram_user_id": tg_user_id, "telegram_chat_id": chat_id},
        )

        conv, _ = TelegramConversation.objects.get_or_create(profile=prof)
        conv.reset()

        lang = _lang_for_profile(prof)
        tg_send_message(chat_id, _MSG[lang]["link_ok"])
        return

    prof = UserProfile.objects.filter(telegram_user_id=tg_user_id).select_related("user").first()
    if not prof:
        tg_send_message(chat_id, _MSG["es"]["not_linked"])
        return

    TelegramLink.objects.update_or_create(
        profile=prof,
        defaults={"telegram_user_id": tg_user_id, "telegram_chat_id": chat_id},
    )

    lang = _lang_for_profile(prof)
    conv, _ = TelegramConversation.objects.get_or_create(profile=prof)

    # estados (compatibles aunque tu model no tenga el constant nuevo)
    STATE_NONE = getattr(TelegramConversation, "STATE_NONE", "none")
    STATE_LOAN_ASK_INSTALLMENTS = getattr(TelegramConversation, "STATE_LOAN_ASK_INSTALLMENTS", "loan_ask_installments")
    STATE_LOAN_ASK_FIRST_DUE = getattr(TelegramConversation, "STATE_LOAN_ASK_FIRST_DUE", "loan_ask_first_due")

    # Reusamos este estado para selección de tarjeta, pero ahora sirve también para drafts
    STATE_TX_ASK_CARD = getattr(TelegramConversation, "STATE_TX_ASK_CARD", "tx_ask_card")

    # NUEVOS estados (strings, sin tocar el model)
    STATE_TX_CONFIRM = "tx_confirm"
    STATE_TX_EDIT_AMOUNT = "tx_edit_amount"
    STATE_TX_EDIT_CURRENCY = "tx_edit_currency"
    STATE_TX_EDIT_DESC = "tx_edit_desc"
    STATE_TX_EDIT_KIND = "tx_edit_kind"
    STATE_TX_WIZ_AMOUNT = "tx_wiz_amount"
    STATE_TX_WIZ_DESC = "tx_wiz_desc"

    # ✅ NUEVO: estados categorías/presupuestos
    STATE_TX_CAT_CHOICE = "tx_cat_choice"
    STATE_TX_CAT_PICK_EXISTING = "tx_cat_pick_existing"
    STATE_TX_CAT_NEW_NAME = "tx_cat_new_name"
    STATE_TX_CAT_NEW_PICK_BUDGET = "tx_cat_new_pick_budget"
    STATE_TX_CAT_NEW_AMOUNT = "tx_cat_new_amount"

    if text.strip().lower() in ("/help", "help", "ayuda"):
        tg_send_message(chat_id, _MSG[lang]["help"])
        return

    # deja “listo” feature
    _ = has_feature(prof.user, FEATURE_LOAN_ALERTS)

    # ------------------------------------------------------------
    # ✅ OCR: leer imagen/PDF y devolver texto
    # ------------------------------------------------------------
    has_media = bool(msg.get("photo") or msg.get("document"))
    if _should_ocr_for_message(text=text, has_media=has_media):
        file_id = _extract_best_file_id_from_msg(msg)
        file_bytes = tg_get_file_bytes(file_id) if file_id else None
        if not file_bytes:
            tg_send_message(chat_id, _MSG[lang]["ocr_failed"])
            return

        ocr_text = ocr_bytes_to_text(file_bytes, lang=lang)
        if not ocr_text:
            tg_send_message(chat_id, _MSG[lang]["ocr_no_text"])
            return

        header = _MSG[lang]["ocr_result_header"]
        tg_send_long_message(chat_id, f"{header}\n\n{ocr_text}")
        return

    # cancelar genérico en cualquier estado interactivo
    if conv.state != STATE_NONE and _is_cancel_card_reply(text):
        conv.reset()
        tg_send_message(chat_id, _MSG[lang]["tx_cancel_ok"])
        return

    # ------------------------------------------------------------
    # ✅ Flujo categorías/presupuesto (MVP por keywords)
    # ------------------------------------------------------------
    if conv.state in (STATE_TX_CAT_CHOICE, STATE_TX_CAT_PICK_EXISTING, STATE_TX_CAT_NEW_NAME,
                      STATE_TX_CAT_NEW_PICK_BUDGET, STATE_TX_CAT_NEW_AMOUNT):

        payload2 = dict(conv.payload or {})
        draft = dict(payload2.get("draft") or {})
        kw = payload2.get("kw") or draft.get("budget_kw") or _kw_from_description(draft.get("description") or "")

        if not draft:
            conv.reset()
            return

        # 1) elección principal
        if conv.state == STATE_TX_CAT_CHOICE:
            choice = (text or "").strip().lower()

            if choice in ("0", "sin", "no", "ninguna"):
                draft["budget_category_id"] = None
                _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
                summary = _draft_summary_text(lang, draft, prof.user)
                tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
                return

            if choice in ("1", "asociar", "existente"):
                if not BudgetCategory:
                    draft["budget_category_id"] = None
                    _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
                    summary = _draft_summary_text(lang, draft, prof.user)
                    tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
                    return

                cats = _list_categories(prof.user)
                if not cats:
                    tg_send_message(chat_id, _MSG[lang]["cat_no_categories"])
                    return

                show = cats[:10]
                _set_state(
                    conv,
                    STATE_TX_CAT_PICK_EXISTING,
                    {"draft": draft, "kw": kw, "cat_ids": [c.id for c in show]},
                )
                tg_send_message(
                    chat_id,
                    _MSG[lang]["cat_pick_existing"].format(kw=kw, cats=_render_categories_prompt(show)),
                )
                return

            if choice in ("2", "crear", "nueva"):
                _set_state(conv, STATE_TX_CAT_NEW_NAME, {"draft": draft, "kw": kw})
                tg_send_message(chat_id, _MSG[lang]["cat_new_ask_name"])
                return

            tg_send_message(chat_id, _MSG[lang]["cat_invalid"])
            return

        # 2) pick categoría existente
        if conv.state == STATE_TX_CAT_PICK_EXISTING:
            if not BudgetCategory:
                conv.reset()
                return

            cat_ids = payload2.get("cat_ids") or []
            cats = list(BudgetCategory.objects.filter(user=prof.user, id__in=cat_ids).order_by("name", "id"))

            max_n = len(cats)
            ch = _parse_choice_1n_or_special(text, max_n=max_n)
            if ch is None or ch in ("0", "N"):
                tg_send_message(chat_id, _MSG[lang]["cat_invalid"])
                return
            if ch == "C":
                conv.reset()
                tg_send_message(chat_id, _MSG[lang]["tx_cancel_ok"])
                return

            idx = int(ch) - 1
            if idx < 0 or idx >= max_n:
                tg_send_message(chat_id, _MSG[lang]["cat_invalid"])
                return

            cat = cats[idx]
            draft["budget_category_id"] = cat.id
            draft["budget_kw"] = kw

            # ✅ guarda mapping agregando keyword a match_keywords
            _append_keyword_to_category(cat, kw)

            _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["cat_linked_ok"].format(kw=kw, cat=_cat_label(cat)))

            summary = _draft_summary_text(lang, draft, prof.user)
            tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
            return

        # 3) crear categoría: pedir nombre
        if conv.state == STATE_TX_CAT_NEW_NAME:
            if not BudgetCategory:
                conv.reset()
                return

            name = (text or "").strip()
            if not name:
                tg_send_message(chat_id, _MSG[lang]["cat_new_ask_name"])
                return

            payload2["new_cat_name"] = name

            # mostramos presupuestos actuales para copiar monto
            buds = _list_monthly_budgets_current_month(prof.user) if MonthlyBudget else []
            show = buds[:10]

            _set_state(
                conv,
                STATE_TX_CAT_NEW_PICK_BUDGET,
                {"draft": draft, "kw": kw, "new_cat_name": name, "bud_ids": [b.id for b in show]},
            )

            buds_txt = _render_monthly_budgets_prompt(show)
            if not show:
                buds_txt = _MSG[lang]["cat_no_budgets"] + "\n\n" + "(0) Saltar\nN) Definir monto nuevo\nC) Cancelar"

            tg_send_message(chat_id, _MSG[lang]["cat_new_pick_existing_budget"].format(buds=buds_txt))
            return

        # 4) elegir presupuesto existente para copiar monto, o N para monto nuevo, o 0 para saltar
        if conv.state == STATE_TX_CAT_NEW_PICK_BUDGET:
            if not BudgetCategory:
                conv.reset()
                return

            bud_ids = payload2.get("bud_ids") or []
            buds = []
            if MonthlyBudget and bud_ids:
                buds = list(MonthlyBudget.objects.filter(user=prof.user, id__in=bud_ids).select_related("category").order_by("id"))

            max_n = len(buds)
            ch = _parse_choice_1n_or_special(text, max_n=max_n)
            if ch is None:
                tg_send_message(chat_id, _MSG[lang]["cat_invalid"])
                return
            if ch == "C":
                conv.reset()
                tg_send_message(chat_id, _MSG[lang]["tx_cancel_ok"])
                return

            # 0 = no crear presupuesto por ahora
            if ch == "0":
                name = payload2.get("new_cat_name") or "Nueva categoría"
                cat = BudgetCategory.objects.create(user=prof.user, name=name, match_keywords=_norm(kw), is_active=True)
                draft["budget_category_id"] = cat.id
                draft["budget_kw"] = kw

                _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
                tg_send_message(chat_id, _MSG[lang]["cat_created_ok"].format(cat=_cat_label(cat)))

                summary = _draft_summary_text(lang, draft, prof.user)
                tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
                return

            # N = pedir monto nuevo
            if ch == "N":
                _set_state(
                    conv,
                    STATE_TX_CAT_NEW_AMOUNT,
                    {"draft": draft, "kw": kw, "new_cat_name": payload2.get("new_cat_name")},
                )
                tg_send_message(chat_id, _MSG[lang]["cat_new_ask_amount"])
                return

            # número = copiar monto de presupuesto existente
            idx = int(ch) - 1
            if idx < 0 or idx >= max_n:
                tg_send_message(chat_id, _MSG[lang]["cat_invalid"])
                return

            picked = buds[idx]
            amt = Decimal(getattr(picked, "amount_clp", Decimal("0")) or Decimal("0")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

            name = payload2.get("new_cat_name") or "Nueva categoría"
            cat = BudgetCategory.objects.create(user=prof.user, name=name, match_keywords=_norm(kw), is_active=True)

            # crea MonthlyBudget del mes actual con el monto copiado
            if MonthlyBudget:
                _ensure_monthly_budget_for_category(prof.user, cat, amt)

            draft["budget_category_id"] = cat.id
            draft["budget_kw"] = kw

            _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["cat_created_ok"].format(cat=_cat_label(cat)))

            summary = _draft_summary_text(lang, draft, prof.user)
            tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
            return

        # 5) monto nuevo
        if conv.state == STATE_TX_CAT_NEW_AMOUNT:
            if not BudgetCategory:
                conv.reset()
                return

            amt = _parse_int_amount_clp(text)
            if amt is None:
                tg_send_message(chat_id, _MSG[lang]["cat_new_ask_amount"])
                return

            name = payload2.get("new_cat_name") or "Nueva categoría"
            cat = BudgetCategory.objects.create(user=prof.user, name=name, match_keywords=_norm(kw), is_active=True)

            if MonthlyBudget:
                _ensure_monthly_budget_for_category(prof.user, cat, amt)

            draft["budget_category_id"] = cat.id
            draft["budget_kw"] = kw

            _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["cat_created_ok"].format(cat=_cat_label(cat)))

            summary = _draft_summary_text(lang, draft, prof.user)
            tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
            return

    # ------------------------------------------------------------
    # Confirmación antes de guardar
    # ------------------------------------------------------------
    if conv.state == STATE_TX_CONFIRM:
        payload2 = dict(conv.payload or {})
        draft = dict(payload2.get("draft") or {})
        if not draft:
            conv.reset()
            return

        choice = (text or "").strip().lower()

        if choice in ("0", "cancelar", "cancel", "c"):
            conv.reset()
            tg_send_message(chat_id, _MSG[lang]["tx_cancel_ok"])
            return

        if choice in ("2", "editar monto", "monto"):
            _set_state(conv, STATE_TX_EDIT_AMOUNT, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["tx_edit_amount_ask"])
            return

        if choice in ("3", "editar moneda", "moneda", "currency"):
            _set_state(conv, STATE_TX_EDIT_CURRENCY, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["tx_edit_currency_ask"])
            return

        if choice in ("4", "editar descripcion", "editar descripción", "descripcion", "descripción", "desc"):
            _set_state(conv, STATE_TX_EDIT_DESC, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["tx_edit_desc_ask"])
            return

        if choice in ("5", "editar tarjeta", "tarjeta", "card"):
            all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
            if not all_cards:
                tg_send_message(chat_id, _MSG[lang]["card_no_cards"])
                return

            is_payment = bool(draft.get("is_card_payment"))
            ask_list = all_cards[:8]
            _set_state(
                conv,
                STATE_TX_ASK_CARD,
                {
                    "draft": draft,
                    "card_candidates": [c.id for c in ask_list],
                    "mode": "payment" if is_payment else "normal",
                    "return_state": STATE_TX_CONFIRM,
                },
            )
            cards_text = _render_cards_for_prompt(ask_list)
            if is_payment:
                tg_send_message(chat_id, _MSG[lang]["card_pay_ask"].format(cards=cards_text))
            else:
                tg_send_message(chat_id, _MSG[lang]["card_ask"].format(cards=cards_text))
            return

        if choice in ("6", "cambiar tipo", "tipo", "type"):
            if draft.get("is_card_payment"):
                summary = _draft_summary_text(lang, draft, prof.user)
                tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_payment"])
                return
            _set_state(conv, STATE_TX_EDIT_KIND, {"draft": draft})
            tg_send_message(chat_id, _MSG[lang]["tx_edit_kind_ask"])
            return

        if choice in ("1", "guardar", "confirmar", "ok", "si", "sí", "yes", "save"):
            if draft.get("is_card_payment") and not draft.get("card_id"):
                all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
                if not all_cards:
                    tg_send_message(chat_id, _MSG[lang]["tx_need_card_for_payment"])
                    return

                ask_list = all_cards[:8]
                _set_state(
                    conv,
                    STATE_TX_ASK_CARD,
                    {
                        "draft": draft,
                        "card_candidates": [c.id for c in ask_list],
                        "mode": "payment",
                        "return_state": STATE_TX_CONFIRM,
                    },
                )
                cards_text = _render_cards_for_prompt(ask_list)
                tg_send_message(chat_id, _MSG[lang]["card_pay_ask"].format(cards=cards_text))
                return

            parsed = _draft_to_parsed(draft)

            card_obj = None
            if draft.get("card_id"):
                card_obj = Card.objects.filter(user=prof.user, is_active=True, id=int(draft["card_id"])).first()

            occurred_at = timezone.now()
            try:
                dt = datetime.fromisoformat(str(draft.get("occurred_at") or ""))
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                occurred_at = dt.astimezone(timezone.get_current_timezone())
            except Exception:
                occurred_at = timezone.now()

            tx, created = create_tx_from_telegram(
                user=prof.user,
                telegram_message_id=int(draft.get("telegram_message_id") or message_id),
                occurred_at=occurred_at,
                parsed=parsed,
                card=card_obj,
            )

            if not created:
                conv.reset()
                tg_send_message(chat_id, _MSG[lang]["tx_dupe"])
                return

            approx = f" ≈ {_fmt_clp(tx.amount_clp)} CLP" if parsed.currency_original == "USD" else ""
            tg_send_message(
                chat_id,
                _MSG[lang]["tx_saved"].format(
                    label=_label(parsed.kind, lang),
                    amount=_money(parsed.amount_original, parsed.currency_original, lang),
                    cur=parsed.currency_original,
                    approx=approx,
                    desc=parsed.description,
                    id=tx.id,
                ),
            )

            if draft.get("is_card_payment"):
                if not card_obj:
                    conv.reset()
                    tg_send_message(chat_id, _MSG[lang]["tx_need_card_for_payment"])
                    return
                ok = _apply_card_payment_to_balance(card_obj, getattr(tx, "amount_clp", Decimal("0")) or Decimal("0"))
                conv.reset()
                if ok:
                    tg_send_message(chat_id, _MSG[lang]["card_payment_applied"].format(id=tx.id, card=_card_label(card_obj)))
                else:
                    tg_send_message(chat_id, _MSG[lang]["card_payment_missing_balance"].format(id=tx.id, card=_card_label(card_obj)))
                return

            conv.reset()
            return

        summary = _draft_summary_text(lang, draft, prof.user)
        kind = draft.get("kind") or "expense"
        is_payment = bool(draft.get("is_card_payment"))
        if is_payment:
            actions = _MSG[lang]["tx_confirm_actions_payment"]
        else:
            actions = _MSG[lang]["tx_confirm_actions_income"] if kind == "income" else _MSG[lang]["tx_confirm_actions_expense"]
        tg_send_message(chat_id, summary + "\n\n" + actions)
        return

    # ------------------------------------------------------------
    # Edición de campos
    # ------------------------------------------------------------
    if conv.state in (STATE_TX_EDIT_AMOUNT, STATE_TX_EDIT_CURRENCY, STATE_TX_EDIT_DESC, STATE_TX_EDIT_KIND):
        payload2 = dict(conv.payload or {})
        draft = dict(payload2.get("draft") or {})
        if not draft:
            conv.reset()
            return

        if conv.state == STATE_TX_EDIT_AMOUNT:
            amt, cur = _parse_amount_and_currency_from_free_text(text)
            if amt is None:
                tg_send_message(chat_id, _MSG[lang]["tx_edit_amount_ask"])
                return
            draft["amount_original"] = str(amt)
            if cur:
                draft["currency_original"] = cur

        elif conv.state == STATE_TX_EDIT_CURRENCY:
            cur = _parse_currency_only(text)
            if not cur:
                tg_send_message(chat_id, _MSG[lang]["tx_edit_currency_ask"])
                return
            draft["currency_original"] = cur

        elif conv.state == STATE_TX_EDIT_DESC:
            desc = (text or "").strip()
            if not desc:
                tg_send_message(chat_id, _MSG[lang]["tx_edit_desc_ask"])
                return
            draft["description"] = desc
            # ✅ recalcula keyword por si cambió la descripción
            draft["budget_kw"] = _kw_from_description(desc)

        elif conv.state == STATE_TX_EDIT_KIND:
            k = _parse_kind_only(text)
            if not k:
                tg_send_message(chat_id, _MSG[lang]["tx_edit_kind_ask"])
                return
            draft["kind"] = k

        _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
        summary = _draft_summary_text(lang, draft, prof.user)
        kind = draft.get("kind") or "expense"
        is_payment = bool(draft.get("is_card_payment"))
        if is_payment:
            actions = _MSG[lang]["tx_confirm_actions_payment"]
        else:
            actions = _MSG[lang]["tx_confirm_actions_income"] if kind == "income" else _MSG[lang]["tx_confirm_actions_expense"]
        tg_send_message(chat_id, summary + "\n\n" + actions)
        return

    # ------------------------------------------------------------
    # Wizard paso a paso
    # ------------------------------------------------------------
    low_cmd = (text or "").strip().lower()

    if conv.state == STATE_NONE and low_cmd in ("gasto", "expense", "ingreso", "income"):
        kind = "expense" if low_cmd in ("gasto", "expense") else "income"
        draft = {
            "kind": kind,
            "amount_original": "",
            "currency_original": "CLP",
            "description": "",
            "telegram_message_id": int(message_id),
            "occurred_at": timezone.now().isoformat(),
            "card_id": None,
            "is_card_payment": False,
            "budget_kw": "",
            "budget_category_id": None,
        }
        _set_state(conv, STATE_TX_WIZ_AMOUNT, {"draft": draft})
        tg_send_message(chat_id, _MSG[lang]["tx_edit_amount_ask"])
        return

    if conv.state == STATE_NONE and any(low_cmd == p for p in _CARD_PAY_PREFIXES):
        all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
        if not all_cards:
            tg_send_message(chat_id, _MSG[lang]["tx_need_card_for_payment"])
            return

        draft = {
            "kind": "expense",
            "amount_original": "",
            "currency_original": "CLP",
            "description": "Pago tarjeta" if lang == "es" else "Card payment",
            "telegram_message_id": int(message_id),
            "occurred_at": timezone.now().isoformat(),
            "card_id": None,
            "is_card_payment": True,
            "budget_kw": "",
            "budget_category_id": None,
        }
        _set_state(conv, STATE_TX_WIZ_AMOUNT, {"draft": draft})
        tg_send_message(chat_id, _MSG[lang]["tx_edit_amount_ask"])
        return

    if conv.state == STATE_TX_WIZ_AMOUNT:
        payload2 = dict(conv.payload or {})
        draft = dict(payload2.get("draft") or {})
        if not draft:
            conv.reset()
            return

        amt, cur = _parse_amount_and_currency_from_free_text(text)
        if amt is None:
            tg_send_message(chat_id, _MSG[lang]["tx_edit_amount_ask"])
            return

        draft["amount_original"] = str(amt)
        draft["currency_original"] = cur or draft.get("currency_original") or "CLP"

        if draft.get("is_card_payment"):
            all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
            if not all_cards:
                conv.reset()
                tg_send_message(chat_id, _MSG[lang]["tx_need_card_for_payment"])
                return

            ask_list = all_cards[:8]
            _set_state(
                conv,
                STATE_TX_ASK_CARD,
                {
                    "draft": draft,
                    "card_candidates": [c.id for c in ask_list],
                    "mode": "payment",
                    "return_state": STATE_TX_CONFIRM,
                },
            )
            cards_text = _render_cards_for_prompt(ask_list)
            tg_send_message(chat_id, _MSG[lang]["card_pay_ask"].format(cards=cards_text))
            return

        _set_state(conv, STATE_TX_WIZ_DESC, {"draft": draft})
        tg_send_message(chat_id, _MSG[lang]["tx_edit_desc_ask"])
        return

    if conv.state == STATE_TX_WIZ_DESC:
        payload2 = dict(conv.payload or {})
        draft = dict(payload2.get("draft") or {})
        if not draft:
            conv.reset()
            return

        desc = (text or "").strip()
        if not desc:
            tg_send_message(chat_id, _MSG[lang]["tx_edit_desc_ask"])
            return

        draft["description"] = desc
        draft["budget_kw"] = _kw_from_description(desc)

        # ✅ NUEVO: antes de confirmar, resolver categoría por keyword (solo gasto normal)
        if BudgetCategory and (draft.get("kind") == "expense") and (not draft.get("is_card_payment")):
            kw = draft.get("budget_kw") or _kw_from_description(desc)
            cat = _find_category_for_keyword(prof.user, kw)
            if cat:
                draft["budget_category_id"] = cat.id
            else:
                _set_state(conv, STATE_TX_CAT_CHOICE, {"draft": draft, "kw": kw})
                tg_send_message(chat_id, _MSG[lang]["cat_unknown"].format(kw=kw))
                return

        if (draft.get("kind") == "expense"):
            all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
            if all_cards:
                ask_list = all_cards[:8]
                _set_state(
                    conv,
                    STATE_TX_ASK_CARD,
                    {
                        "draft": draft,
                        "card_candidates": [c.id for c in ask_list],
                        "mode": "normal",
                        "return_state": STATE_TX_CONFIRM,
                    },
                )
                cards_text = _render_cards_for_prompt(ask_list)
                tg_send_message(chat_id, _MSG[lang]["card_ask"].format(cards=cards_text))
                return

        _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
        summary = _draft_summary_text(lang, draft, prof.user)
        kind = draft.get("kind") or "expense"
        actions = _MSG[lang]["tx_confirm_actions_income"] if kind == "income" else _MSG[lang]["tx_confirm_actions_expense"]
        tg_send_message(chat_id, summary + "\n\n" + actions)
        return

    # ------------------------------------------------------------
    # Selección de tarjeta
    # ------------------------------------------------------------
    if conv.state == STATE_TX_ASK_CARD:
        payload2 = dict(conv.payload or {})
        draft = dict(payload2.get("draft") or {})
        card_ids = payload2.get("card_candidates") or []
        mode = (payload2.get("mode") or "normal").lower()

        if not draft:
            conv.reset()
            return

        if _is_cancel_card_reply(text):
            _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
            summary = _draft_summary_text(lang, draft, prof.user)
            kind = draft.get("kind") or "expense"
            is_payment = bool(draft.get("is_card_payment"))
            if is_payment:
                actions = _MSG[lang]["tx_confirm_actions_payment"]
            else:
                actions = _MSG[lang]["tx_confirm_actions_income"] if kind == "income" else _MSG[lang]["tx_confirm_actions_expense"]
            tg_send_message(chat_id, summary + "\n\n" + actions)
            return

        if not card_ids:
            card_ids = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id").values_list("id", flat=True))

        if not card_ids:
            conv.reset()
            tg_send_message(chat_id, _MSG[lang]["card_no_cards"])
            return

        max_n = min(len(card_ids), 8)

        choice = _parse_card_choice_number(text, max_n=max_n)
        if choice is not None:
            if mode == "payment" and choice == 0:
                tg_send_message(chat_id, _MSG[lang]["card_pay_not_found"])
                return

            if choice == 0:
                draft["card_id"] = None
                _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
                summary = _draft_summary_text(lang, draft, prof.user)
                actions = _MSG[lang]["tx_confirm_actions_expense"]
                tg_send_message(chat_id, summary + "\n\n" + actions)
                return

            idx = choice - 1
            if idx < 0 or idx >= max_n:
                tg_send_message(chat_id, _MSG[lang]["card_pay_not_found"] if mode == "payment" else _MSG[lang]["card_not_found"])
                return

            chosen_id = int(card_ids[idx])
            chosen = Card.objects.filter(user=prof.user, is_active=True, id=chosen_id).first()
            if not chosen:
                tg_send_message(chat_id, _MSG[lang]["card_pay_not_found"] if mode == "payment" else _MSG[lang]["card_not_found"])
                return

            draft["card_id"] = chosen.id

            _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
            summary = _draft_summary_text(lang, draft, prof.user)
            if draft.get("is_card_payment"):
                actions = _MSG[lang]["tx_confirm_actions_payment"]
            else:
                kind = draft.get("kind") or "expense"
                actions = _MSG[lang]["tx_confirm_actions_income"] if kind == "income" else _MSG[lang]["tx_confirm_actions_expense"]
            tg_send_message(chat_id, summary + "\n\n" + actions)
            return

        if _is_skip_card_reply(text):
            if mode == "payment":
                tg_send_message(chat_id, _MSG[lang]["card_pay_not_found"])
                return
            draft["card_id"] = None
            _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
            summary = _draft_summary_text(lang, draft, prof.user)
            actions = _MSG[lang]["tx_confirm_actions_expense"]
            tg_send_message(chat_id, summary + "\n\n" + actions)
            return

        chosen, _ = _resolve_card_from_text(prof.user, text)
        if not chosen:
            tg_send_message(chat_id, _MSG[lang]["card_pay_not_found"] if mode == "payment" else _MSG[lang]["card_not_found"])
            return

        draft["card_id"] = chosen.id
        _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
        summary = _draft_summary_text(lang, draft, prof.user)
        if draft.get("is_card_payment"):
            actions = _MSG[lang]["tx_confirm_actions_payment"]
        else:
            kind = draft.get("kind") or "expense"
            actions = _MSG[lang]["tx_confirm_actions_income"] if kind == "income" else _MSG[lang]["tx_confirm_actions_expense"]
        tg_send_message(chat_id, summary + "\n\n" + actions)
        return

    # ------------------------------------------------------------
    # Conversación: completar préstamo
    # ------------------------------------------------------------
    if conv.state != STATE_NONE:
        if conv.state == STATE_LOAN_ASK_INSTALLMENTS:
            m = re.search(r"\d{1,3}", text.strip())
            if not m:
                tg_send_message(chat_id, _MSG[lang]["loan_bad_installments"])
                return

            n = int(m.group(0))
            if n < 1 or n > 120:
                tg_send_message(chat_id, _MSG[lang]["loan_bad_installments"])
                return

            payload2 = dict(conv.payload or {})
            payload2["installments_count"] = n
            conv.state = STATE_LOAN_ASK_FIRST_DUE
            conv.payload = payload2
            conv.save(update_fields=["state", "payload", "updated_at"])

            tg_send_message(chat_id, _MSG[lang]["loan_ask_first_due"])
            return

        if conv.state == STATE_LOAN_ASK_FIRST_DUE:
            d = _parse_date_yyyy_mm_dd(text.strip())
            if not d:
                tg_send_message(chat_id, _MSG[lang]["loan_bad_date"])
                return

            payload2 = dict(conv.payload or {})
            payload2["first_due_date"] = d.isoformat()

            person = payload2["person_name"]
            currency = payload2["currency_original"]
            amount = Decimal(str(payload2["amount_original"]))
            direction = payload2["direction"]
            n = int(payload2["installments_count"])

            principal_clp, fx_rate, fx_source = _loan_principal_clp(amount, currency)

            loan = Loan.objects.create(
                user=prof.user,
                direction=direction,
                person_name=person,
                principal_original=amount,
                currency_original=currency,
                principal_clp=principal_clp,
                start_date=timezone.localdate(),
                first_due_date=d,
                installments_count=n,
                frequency=Loan.FREQ_MONTHLY,
                note=(f"FX {fx_source} {fx_rate}" if fx_rate else ""),
                telegram_origin_message_id=message_id,
            )
            loan.build_installments(replace_if_safe=True)

            conv.reset()

            approx = f" ≈ {_fmt_clp(principal_clp)} CLP" if currency == "USD" else ""
            tg_send_message(
                chat_id,
                _MSG[lang]["loan_created"].format(
                    amount=_money(amount, currency, lang),
                    cur=currency,
                    approx=approx,
                    person=person,
                    n=n,
                    due=d.isoformat(),
                ),
            )
            return

    # ------------------------------------------------------------
    # Delete commands
    # ------------------------------------------------------------
    is_del, tx_id, is_last = _parse_delete_cmd(text)
    if is_del:
        if is_last:
            tx = Transaction.objects.filter(user=prof.user).order_by("-occurred_at", "-id").first()
            if not tx:
                tg_send_message(chat_id, _MSG[lang]["delete_not_found"])
                return
        else:
            if not tx_id:
                tg_send_message(chat_id, _MSG[lang]["delete_need_id"])
                return
            tx = Transaction.objects.filter(user=prof.user, id=tx_id).first()
            if not tx:
                tg_send_message(chat_id, _MSG[lang]["delete_not_found"])
                return

        label = _label(tx.kind, lang)
        cur = getattr(tx, "currency_original", "CLP")
        amt = getattr(tx, "amount_original", None) or getattr(tx, "amount_clp", Decimal("0"))
        desc = (getattr(tx, "description", "") or "—")

        tx_id_val = tx.id
        tx.delete()

        tg_send_message(
            chat_id,
            _MSG[lang]["delete_ok"].format(
                label=label,
                amount=_money(Decimal(amt), cur, lang),
                cur=cur,
                desc=desc,
                id=tx_id_val,
            ),
        )
        return

    # ------------------------------------------------------------
    # Movements (single day OR range)
    # ------------------------------------------------------------
    d1, d2 = _parse_movements_single_or_range(text)
    if d1:
        if d2:
            if not has_feature(prof.user, FEATURE_TX_QUERY_RANGE):
                tg_send_message(chat_id, _MSG[lang]["upgrade"])
                return

            a = min(d1, d2)
            b = max(d1, d2)

            qs = Transaction.objects.filter(
                user=prof.user,
                occurred_at__date__gte=a,
                occurred_at__date__lte=b,
            ).order_by("occurred_at", "id")[:60]

            if not qs.exists():
                tg_send_message(chat_id, _MSG[lang]["movements_range_none"])
                return

            lines = [_MSG[lang]["movements_range_header"].format(a=a.isoformat(), b=b.isoformat())]
            for tx in qs:
                cur = getattr(tx, "currency_original", "CLP")
                amt = getattr(tx, "amount_original", None) or getattr(tx, "amount_clp", Decimal("0"))
                desc = (getattr(tx, "description", "") or "—")
                lines.append(f"ID {tx.id} · {_label(tx.kind, lang)} {_money(Decimal(amt), cur, lang)} {cur} · {desc}")

            tg_send_message(chat_id, "\n".join(lines))
            return

        qs = Transaction.objects.filter(user=prof.user, occurred_at__date=d1).order_by("occurred_at", "id")[:30]
        if not qs.exists():
            tg_send_message(chat_id, _MSG[lang]["movements_none"])
            return

        lines = [_MSG[lang]["movements_header"].format(day=d1.isoformat())]
        for tx in qs:
            cur = getattr(tx, "currency_original", "CLP")
            amt = getattr(tx, "amount_original", None) or getattr(tx, "amount_clp", Decimal("0"))
            desc = (getattr(tx, "description", "") or "—")
            lines.append(f"ID {tx.id} · {_label(tx.kind, lang)} {_money(Decimal(amt), cur, lang)} {cur} · {desc}")

        tg_send_message(chat_id, "\n".join(lines))
        return

    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------
    ym = _parse_summary_query(text)
    if ym:
        y, mo = ym
        start = date(y, mo, 1)
        end = date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)

        qs = Transaction.objects.filter(user=prof.user, occurred_at__date__gte=start, occurred_at__date__lt=end)
        total_exp = qs.filter(kind=Transaction.KIND_EXPENSE).aggregate(s=models.Sum("amount_clp")).get("s") or Decimal("0")
        total_inc = qs.filter(kind=Transaction.KIND_INCOME).aggregate(s=models.Sum("amount_clp")).get("s") or Decimal("0")
        bal = total_inc - total_exp

        msg_out = (
            _MSG[lang]["summary_header"].format(ym=f"{y}-{mo:02d}")
            + "\n"
            + f"{_label('income', lang)}: {_fmt_clp(total_inc)} CLP\n"
            + f"{_label('expense', lang)}: {_fmt_clp(total_exp)} CLP\n"
            + f"Balance: {_fmt_clp(bal)} CLP"
        )
        tg_send_message(chat_id, msg_out)
        return

    # ------------------------------------------------------------
    # Loans list
    # ------------------------------------------------------------
    if text.strip().lower() in ("prestamos", "préstamos", "loans"):
        qs = Loan.objects.filter(user=prof.user, status=Loan.STATUS_ACTIVE).order_by("-id")[:20]
        if not qs.exists():
            tg_send_message(chat_id, _MSG[lang]["loans_none"])
            return

        lines = [_MSG[lang]["loans_header"]]
        for loan in qs:
            approx = f" ≈ {_fmt_clp(loan.principal_clp)} CLP" if loan.currency_original == "USD" else ""
            lines.append(
                f"ID {loan.id} · {loan.person_name} · {loan.principal_original} {loan.currency_original}{approx} · {loan.installments_count} cuotas · primer venc {loan.first_due_date or '—'}"
            )
        tg_send_message(chat_id, "\n".join(lines))
        return

    # ------------------------------------------------------------
    # Loan creation (parse)
    # ------------------------------------------------------------
    pl = parse_text_to_loan(text)
    if pl:
        if not pl.installments:
            conv.state = STATE_LOAN_ASK_INSTALLMENTS
            conv.payload = dict(
                direction=pl.direction,
                person_name=pl.person_name,
                amount_original=str(pl.amount_original),
                currency_original=pl.currency_original,
            )
            conv.save(update_fields=["state", "payload", "updated_at"])
            tg_send_message(chat_id, _MSG[lang]["loan_ask_installments"])
            return

        if not pl.first_due:
            conv.state = STATE_LOAN_ASK_FIRST_DUE
            conv.payload = dict(
                direction=pl.direction,
                person_name=pl.person_name,
                amount_original=str(pl.amount_original),
                currency_original=pl.currency_original,
                installments_count=int(pl.installments),
            )
            conv.save(update_fields=["state", "payload", "updated_at"])
            tg_send_message(chat_id, _MSG[lang]["loan_ask_first_due"])
            return

        principal_clp, fx_rate, fx_source = _loan_principal_clp(pl.amount_original, pl.currency_original)

        loan = Loan.objects.create(
            user=prof.user,
            direction=pl.direction,
            person_name=pl.person_name,
            principal_original=pl.amount_original,
            currency_original=pl.currency_original,
            principal_clp=principal_clp,
            start_date=timezone.localdate(),
            first_due_date=pl.first_due,
            installments_count=int(pl.installments),
            frequency=Loan.FREQ_MONTHLY,
            note=(f"FX {fx_source} {fx_rate}" if fx_rate else ""),
            telegram_origin_message_id=message_id,
        )
        loan.build_installments(replace_if_safe=True)

        approx = f" ≈ {_fmt_clp(principal_clp)} CLP" if pl.currency_original == "USD" else ""
        tg_send_message(
            chat_id,
            _MSG[lang]["loan_created"].format(
                amount=_money(pl.amount_original, pl.currency_original, lang),
                cur=pl.currency_original,
                approx=approx,
                person=pl.person_name,
                n=int(pl.installments),
                due=pl.first_due.isoformat(),
            ),
        )
        return

    # ------------------------------------------------------------
    # One-shot parse: Pago de tarjeta
    # ------------------------------------------------------------
    parsed_pay = parse_text_to_card_payment(text)
    if parsed_pay:
        all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
        if not all_cards:
            tg_send_message(chat_id, _MSG[lang]["tx_need_card_for_payment"])
            return

        draft = _draft_from_parsed(parsed_pay, telegram_message_id=int(message_id), occurred_at_iso=timezone.now().isoformat())
        draft["is_card_payment"] = True
        draft["description"] = "Pago tarjeta" if lang == "es" else "Card payment"

        chosen_card, _cands = _resolve_card_from_text(prof.user, parsed_pay.raw_text)
        if chosen_card:
            draft["card_id"] = chosen_card.id

        if not draft.get("card_id"):
            ask_list = all_cards[:8]
            _set_state(
                conv,
                STATE_TX_ASK_CARD,
                {"draft": draft, "card_candidates": [c.id for c in ask_list], "mode": "payment", "return_state": STATE_TX_CONFIRM},
            )
            cards_text = _render_cards_for_prompt(ask_list)
            tg_send_message(chat_id, _MSG[lang]["card_pay_ask"].format(cards=cards_text))
            return

        _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
        summary = _draft_summary_text(lang, draft, prof.user)
        tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_payment"])
        return

    # ------------------------------------------------------------
    # One-shot parse: Normal TX
    # ------------------------------------------------------------
    parsed = parse_text_to_tx(text)
    if not parsed:
        tg_send_message(chat_id, _MSG[lang]["tx_parse_fail"])
        return

    draft = _draft_from_parsed(parsed, telegram_message_id=int(message_id), occurred_at_iso=timezone.now().isoformat())

    # ✅ NUEVO: resolver categoría por keyword antes de seguir (solo gastos normales)
    if BudgetCategory and parsed.kind == "expense":
        kw = draft.get("budget_kw") or _kw_from_description(parsed.description or "")
        cat = _find_category_for_keyword(prof.user, kw)
        if cat:
            draft["budget_category_id"] = cat.id
        else:
            _set_state(conv, STATE_TX_CAT_CHOICE, {"draft": draft, "kw": kw})
            tg_send_message(chat_id, _MSG[lang]["cat_unknown"].format(kw=kw))
            return

    all_cards = list(Card.objects.filter(user=prof.user, is_active=True).order_by("name", "id"))
    if all_cards and parsed.kind == "expense":
        chosen_card, candidates = _resolve_card_from_text(prof.user, parsed.raw_text)
        if chosen_card:
            draft["card_id"] = chosen_card.id

        if not draft.get("card_id"):
            should_ask = _text_mentions_card(parsed.raw_text)
            if not should_ask and candidates:
                should_ask = True

            if should_ask:
                ask_list = (candidates if candidates else all_cards)[:8]
                _set_state(
                    conv,
                    STATE_TX_ASK_CARD,
                    {"draft": draft, "card_candidates": [c.id for c in ask_list], "mode": "normal", "return_state": STATE_TX_CONFIRM},
                )
                cards_text = _render_cards_for_prompt(ask_list)
                tg_send_message(chat_id, _MSG[lang]["card_ask"].format(cards=cards_text))
                return

    _set_state(conv, STATE_TX_CONFIRM, {"draft": draft})
    summary = _draft_summary_text(lang, draft, prof.user)
    if parsed.kind == "income":
        tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_income"])
    else:
        tg_send_message(chat_id, summary + "\n\n" + _MSG[lang]["tx_confirm_actions_expense"])
    return