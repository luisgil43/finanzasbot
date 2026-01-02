# accounts/templatetags/formatting.py
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _format_number_es(value: Decimal, decimals: int) -> str:
    """
    Formato ES (Chile-friendly):
    - Miles con punto: 1.234.567
    - Decimales con coma: 1.234,56
    """
    q = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
    v = value.quantize(q, rounding=ROUND_HALF_UP)

    s = f"{v:f}"
    if "." in s:
        int_part, dec_part = s.split(".", 1)
    else:
        int_part, dec_part = s, ""

    # agrupar miles con "."
    sign = ""
    if int_part.startswith("-"):
        sign = "-"
        int_part = int_part[1:]

    chunks = []
    while int_part:
        chunks.append(int_part[-3:])
        int_part = int_part[:-3]
    int_grouped = ".".join(reversed(chunks)) if chunks else "0"

    if decimals == 0:
        return f"{sign}{int_grouped}"

    dec_part = (dec_part + ("0" * decimals))[:decimals]
    return f"{sign}{int_grouped},{dec_part}"


@register.filter(name="money")
def money(value, currency: str = "CLP") -> str:
    """
    Uso: {{ amount|money:"CLP" }} o {{ amount|money:profile.currency }}
    - CLP => 0 decimales
    - USD => 2 decimales
    """
    cur = (currency or "CLP").upper()
    dec = 0 if cur == "CLP" else 2
    v = _to_decimal(value)
    return _format_number_es(v, dec)