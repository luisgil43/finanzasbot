from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional, Tuple

from django.core.files.storage import default_storage
from django.utils import timezone

from transactions.fx import get_usd_to_clp
from transactions.models import Transaction


@dataclass(frozen=True)
class ParsedReceipt:
    amount: Optional[Decimal]
    currency: str
    occurred_date: Optional[date]
    merchant: str
    description: str
    raw_text: str


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s


def _to_decimal_num(s: str, currency: str) -> Optional[Decimal]:
    raw = (s or "").strip().replace(" ", "")
    raw = re.sub(r"[^0-9\.,\-]", "", raw)
    if not raw:
        return None

    # Heurística separadores
    if raw.count(".") and raw.count(","):
        if raw.rfind(".") > raw.rfind(","):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(","):
        # CLP normalmente coma es miles, USD puede ser decimal
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
        return None


def _detect_currency(text: str) -> str:
    low = _norm(text)
    if "usd" in low or "us$" in low or "$us" in low:
        return "USD"
    # Si aparece $ y no aparece CLP explícito, en boletas chilenas igual suele ser CLP.
    return "CLP"


def _parse_date_any(text: str) -> Optional[date]:
    # dd-mm-yyyy / dd/mm/yyyy
    m = re.search(r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except Exception:
            return None

    # yyyy-mm-dd
    m = re.search(r"\b(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except Exception:
            return None

    return None


def _guess_merchant(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    # primera línea “no genérica”
    bad = {"boleta", "ticket", "documento", "factura", "rut", "sii", "giro", "direccion", "total"}
    for ln in lines[:8]:
        n = _norm(ln)
        if len(n) >= 3 and not any(w in n for w in bad):
            return ln[:120]
    return lines[0][:120]


def parse_receipt_text(raw_text: str) -> ParsedReceipt:
    text = raw_text or ""
    currency = _detect_currency(text)
    occurred = _parse_date_any(text)
    merchant = _guess_merchant(text)

    # Buscar montos candidatos: prioriza líneas con TOTAL / A PAGAR
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    best_amount: Optional[Decimal] = None

    preferred_keywords = ("total", "a pagar", "monto total", "total a pagar", "importe", "total venta")
    for ln in lines:
        n = _norm(ln)
        if any(k in n for k in preferred_keywords):
            m = re.search(r"(-?\d[\d\.,]*)", ln)
            if m:
                amt = _to_decimal_num(m.group(1), currency)
                if amt and amt > 0:
                    best_amount = amt
                    break

    # Fallback: mayor número encontrado (suele ser el total)
    if best_amount is None:
        nums = re.findall(r"(-?\d[\d\.,]*)", text)
        candidates = []
        for s in nums:
            amt = _to_decimal_num(s, currency)
            if amt and amt > 0:
                candidates.append(amt)
        if candidates:
            best_amount = max(candidates)

    # Descripción sugerida
    desc = merchant or "Boleta"

    return ParsedReceipt(
        amount=best_amount,
        currency=currency,
        occurred_date=occurred,
        merchant=merchant,
        description=desc,
        raw_text=text,
    )


def extract_text_from_image(storage_name: str) -> Tuple[str, Optional[str]]:
    """
    Retorna (text, error). Si no hay OCR disponible, text puede venir vacío.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return ("", "Falta Pillow (PIL). Instala: pip install Pillow")

    try:
        import pytesseract  # type: ignore
    except Exception:
        return ("", "OCR no disponible (pytesseract). Instala: pip install pytesseract y tesseract-ocr en el servidor")

    try:
        with default_storage.open(storage_name, "rb") as f:
            img = Image.open(f)
            img = img.convert("RGB")
            # idioma: spa + eng si está disponible
            try:
                text = pytesseract.image_to_string(img, lang="spa+eng")
            except Exception:
                text = pytesseract.image_to_string(img)
            return (text or "", None)
    except Exception as e:
        return ("", f"OCR falló: {e}")


def create_transaction_from_receipt(
    *,
    user,
    kind: str,
    amount: Decimal,
    currency: str,
    occurred_at,
    description: str,
    card=None,
) -> Transaction:
    occurred_at = occurred_at or timezone.now()

    if currency == "USD":
        fx = get_usd_to_clp()
        fx_rate = (fx.rate or Decimal("1")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        fx_source = fx.source or "fx"
        fx_timestamp = timezone.now()
        amount_clp = (Decimal(amount) * fx_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        fx_rate = Decimal("1")
        fx_source = "base"
        fx_timestamp = timezone.now()
        amount_clp = Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    tx = Transaction.objects.create(
        user=user,
        kind=kind,
        description=description or "Boleta",
        occurred_at=occurred_at,
        amount_original=Decimal(amount),
        currency_original=currency,
        amount_clp=amount_clp,
        fx_rate=fx_rate,
        fx_source=fx_source,
        fx_timestamp=fx_timestamp,
        card=card,
    )
    return tx